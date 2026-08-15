"""Delegated asset creation — investor requests + grant lifecycle (Milestone 1).

The guard helpers at the top are pure and DB-free so they can be unit-tested
without a database fixture (see tests/test_delegation_guards.py). Endpoints
below must delegate every authorisation decision to them rather than
re-implementing the rules inline.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user, get_db
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.permissions import Role
from app.models.advisor_client import AdvisorClient
from app.models.delegation import (
    AdvisorRequest,
    AdvisorRequestStatus,
    AssetDelegationGrant,
    GrantStatus,
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

#: How long an unconsumed grant stays usable. Bounds only the create window --
#: once consumed, edit rights are governed by asset_access (Milestone 3).
DEFAULT_GRANT_TTL_DAYS = 30


# -- Guard helpers (pure, DB-free, unit-tested) -------------------------------

def ensure_request_is_cancellable(request, user) -> None:
    """An investor may withdraw only their own, still-pending request."""
    if str(request.investor_id) != str(user.id):
        raise ForbiddenException(
            "You can only cancel your own request.",
            code="NOT_REQUEST_OWNER",
        )
    if request.status != AdvisorRequestStatus.PENDING.value:
        raise BadRequestException(
            f"Only a pending request can be cancelled (this one is {request.status})."
        )


def ensure_request_is_decidable(request) -> None:
    """Approve/reject is valid exactly once, from PENDING."""
    if request.status != AdvisorRequestStatus.PENDING.value:
        raise ConflictException(f"This request was already {request.status}.")


def grant_is_usable(grant, now: datetime) -> bool:
    """True when a grant may still be consumed to create an asset.

    Expiry is exclusive: a grant expiring exactly `now` is spent.
    """
    if grant.status != GrantStatus.ACTIVE.value:
        return False
    if grant.expires_at is not None and grant.expires_at <= now:
        return False
    return True


def ensure_can_revoke_grant(grant, user) -> None:
    """Only the investor the grant is for, or an admin, may revoke it.

    Deliberately excludes the advisor holding the grant -- revocation is a
    control the client side of the relationship holds, not the delegate.
    """
    is_owner = str(grant.investor_id) == str(user.id)
    is_admin = user.role == Role.ADMIN
    if not (is_owner or is_admin):
        raise ForbiddenException(
            "Only the investor or an admin can revoke this authorisation.",
            code="CANNOT_REVOKE_GRANT",
        )
    if grant.status != GrantStatus.ACTIVE.value:
        raise BadRequestException(
            f"Only an active authorisation can be revoked (this one is {grant.status})."
        )


# -- Serialisers --------------------------------------------------------------

def _person(user: Optional[User]) -> Optional[Dict[str, Any]]:
    if not user:
        return None
    name = " ".join(p for p in [user.first_name, user.last_name] if p).strip()
    return {"id": str(user.id), "name": name or user.email, "email": user.email}


def serialize_request(req: AdvisorRequest, advisor: Optional[User] = None) -> Dict[str, Any]:
    return {
        "id": str(req.id),
        "investor_id": str(req.investor_id),
        "requested_advisor_id": str(req.requested_advisor_id) if req.requested_advisor_id else None,
        "requested_advisor": _person(advisor),
        "note": req.note,
        "status": req.status,
        "decision_reason": req.decision_reason,
        "decided_at": req.decided_at.isoformat() if req.decided_at else None,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


def serialize_grant(
    grant: AssetDelegationGrant,
    advisor: Optional[User] = None,
    investor: Optional[User] = None,
) -> Dict[str, Any]:
    return {
        "id": str(grant.id),
        "investor_id": str(grant.investor_id),
        "advisor_id": str(grant.advisor_id),
        "investor": _person(investor),
        "advisor": _person(advisor),
        "status": grant.status,
        "asset_id": str(grant.asset_id) if grant.asset_id else None,
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "consumed_at": grant.consumed_at.isoformat() if grant.consumed_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "created_at": grant.created_at.isoformat() if grant.created_at else None,
    }


def new_grant_expiry(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)) + timedelta(days=DEFAULT_GRANT_TTL_DAYS)


# -- On-behalf asset creation (Milestone 2) -----------------------------------

NO_ACTIVE_GRANT = "NO_ACTIVE_GRANT"


async def acquire_creation_grant(db: AsyncSession, user: User, on_behalf_of):
    """Lock the advisor's single-use grant and return (investor_account, grant).

    Row-locked with FOR UPDATE so two concurrent creates cannot both consume the
    same grant -- the loser sees it already CONSUMED and is rejected.

    Returns the INVESTOR's account deliberately: the asset belongs to them, and
    the plan/asset limit must be charged to their subscription, never the
    advisor's.
    """
    from app.models.account import Account

    if user.role != Role.ADVISOR:
        raise ForbiddenException(
            "Only an advisor can create an asset on behalf of an investor.",
            code="ADVISOR_ROLE_REQUIRED",
        )

    grant = (await db.execute(
        select(AssetDelegationGrant)
        .where(
            AssetDelegationGrant.investor_id == on_behalf_of,
            AssetDelegationGrant.advisor_id == user.id,
            AssetDelegationGrant.status == GrantStatus.ACTIVE.value,
        )
        .with_for_update()
    )).scalar_one_or_none()

    if grant is None or not grant_is_usable(grant, datetime.now(timezone.utc)):
        raise ForbiddenException(
            "You do not have an active authorisation to add an asset for this investor.",
            # Literal on purpose — see the note in advisor.py's NOT_YOUR_CLIENT
            # raise: the drift guard only sees string literals at raise sites.
            code="NO_ACTIVE_GRANT",
        )

    account = (await db.execute(
        select(Account).where(Account.user_id == on_behalf_of)
    )).scalar_one_or_none()
    if not account:
        raise NotFoundException("Account", str(on_behalf_of))

    return account, grant


def consume_creation_grant(grant: AssetDelegationGrant, asset_id) -> None:
    """Mark the grant spent on `asset_id`.

    Caller must invoke this BEFORE its commit so the asset row and the consumed
    grant land in the same transaction -- otherwise a crash in between would
    leave a grant that can be spent twice.
    """
    grant.status = GrantStatus.CONSUMED.value
    grant.asset_id = asset_id
    grant.consumed_at = datetime.now(timezone.utc)


async def resolve_asset_actor_context(db: AsyncSession, user: User, asset_id):
    """Who owns `asset_id`, and may `user` act on it? -> (owner_user, account, grant).

    Returns the OWNER's user and account, so every downstream gate -- verified
    status, subscription feature, KYB, per-plan limits -- is evaluated against
    the investor who owns the asset rather than whoever is holding the keyboard.

    Two ways to qualify:
      * the caller owns the asset (unchanged behaviour), or
      * the caller is the advisor who created it under a still-unlocked grant.

    Raises NotFound if neither holds, matching the existing "asset not found
    under your account" behaviour rather than leaking that the asset exists.
    """
    from app.models.account import Account
    from app.models.asset import Asset

    own_account = (await db.execute(
        select(Account).where(Account.user_id == user.id)
    )).scalar_one_or_none()

    if own_account is not None:
        owned = (await db.execute(
            select(Asset).where(Asset.id == asset_id, Asset.account_id == own_account.id)
        )).scalar_one_or_none()
        if owned is not None:
            return user, own_account, None

    grant = await find_edit_grant(db, user, asset_id)
    if grant is None:
        raise NotFoundException("Asset", str(asset_id))

    owner = (await db.execute(
        select(User).where(User.id == grant.investor_id)
    )).scalar_one_or_none()
    owner_account = (await db.execute(
        select(Account).where(Account.user_id == grant.investor_id)
    )).scalar_one_or_none()
    if owner is None or owner_account is None:
        raise NotFoundException("Account", str(grant.investor_id))

    return owner, owner_account, grant


async def find_edit_grant(db: AsyncSession, user: User, asset_id):
    """The grant letting `user` still edit `asset_id`, if any.

    CONSUMED means "created, not yet confirmed by the investor" -- decision D1,
    so the advisor can fix a typo without a fresh admin-approved request. LOCKED
    and REVOKED both end edit rights; the advisor keeps read access via
    /advisor/clients/{id}/assets either way.
    """
    return (await db.execute(
        select(AssetDelegationGrant).where(
            AssetDelegationGrant.asset_id == asset_id,
            AssetDelegationGrant.advisor_id == user.id,
            AssetDelegationGrant.status == GrantStatus.CONSUMED.value,
        )
    )).scalar_one_or_none()


# -- Investor endpoints -------------------------------------------------------

class CreateRequestBody(BaseModel):
    requested_advisor_id: Optional[UUID] = None
    note: Optional[str] = Field(default=None, max_length=2000)


def _ensure_investor(user: User) -> None:
    if user.role != Role.INVESTOR:
        raise ForbiddenException(
            "Only investors can request an advisor.",
            code="INVESTOR_ROLE_REQUIRED",
        )


@router.get("/directory", response_model=Dict[str, Any])
async def list_advisor_directory(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Advisors an investor may name in a request -- id + display name only.

    Deliberately minimal: this is a picker, not a staff directory.
    """
    _ensure_investor(current_user)
    rows = (await db.execute(
        select(User).where(User.role == Role.ADVISOR, User.is_active.is_(True))
        .order_by(User.first_name, User.last_name)
    )).scalars().all()
    return {"success": True, "data": [_person(a) for a in rows]}


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_advisor_request(
    body: CreateRequestBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Investor asks an admin to allot them an advisor."""
    _ensure_investor(current_user)

    existing = (await db.execute(
        select(AdvisorRequest).where(
            AdvisorRequest.investor_id == current_user.id,
            AdvisorRequest.status == AdvisorRequestStatus.PENDING.value,
        )
    )).scalar_one_or_none()
    if existing:
        raise ConflictException("You already have a pending advisor request.")

    advisor = None
    if body.requested_advisor_id:
        advisor = (await db.execute(
            select(User).where(User.id == body.requested_advisor_id)
        )).scalar_one_or_none()
        if not advisor:
            raise NotFoundException("User", str(body.requested_advisor_id))
        if advisor.role != Role.ADVISOR:
            raise BadRequestException("The requested user is not an advisor.")

    req = AdvisorRequest(
        investor_id=current_user.id,
        requested_advisor_id=advisor.id if advisor else None,
        note=body.note,
        status=AdvisorRequestStatus.PENDING.value,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    # Notify every admin so the queue does not depend on polling.
    from app.models.notification import NotificationType
    from app.services.notification_service import NotificationService

    admins = (await db.execute(select(User).where(User.role == Role.ADMIN))).scalars().all()
    investor_name = _person(current_user)["name"]
    for admin in admins:
        await NotificationService.notify_user(
            db, admin.id, NotificationType.GENERAL,
            "Advisor request submitted",
            f"{investor_name} has requested an advisor.",
            None,
        )

    logger.info(f"Investor {current_user.id} submitted advisor request {req.id}")
    return {"success": True, "data": serialize_request(req, advisor)}


@router.get("/me", response_model=Dict[str, Any])
async def list_my_advisor_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The investor's own request history plus their current advisor, if any."""
    _ensure_investor(current_user)

    Advisor = aliased(User)
    rows = (await db.execute(
        select(AdvisorRequest, Advisor)
        .outerjoin(Advisor, AdvisorRequest.requested_advisor_id == Advisor.id)
        .where(AdvisorRequest.investor_id == current_user.id)
        .order_by(AdvisorRequest.created_at.desc())
    )).all()

    assignment = (await db.execute(
        select(AdvisorClient, User)
        .join(User, AdvisorClient.advisor_id == User.id)
        .where(AdvisorClient.client_id == current_user.id)
    )).first()

    return {
        "success": True,
        "data": {
            "requests": [serialize_request(r, a) for r, a in rows],
            "current_advisor": _person(assignment[1]) if assignment else None,
        },
    }


@router.delete("/{request_id}", response_model=Dict[str, Any])
async def cancel_advisor_request(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Investor withdraws their own pending request."""
    req = (await db.execute(
        select(AdvisorRequest).where(AdvisorRequest.id == request_id)
    )).scalar_one_or_none()
    if not req:
        raise NotFoundException("AdvisorRequest", str(request_id))

    ensure_request_is_cancellable(req, current_user)

    req.status = AdvisorRequestStatus.CANCELLED.value
    req.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(req)

    logger.info(f"Investor {current_user.id} cancelled advisor request {req.id}")
    return {"success": True, "data": serialize_request(req)}


# -- Grant endpoints (separate router: /delegation-grants) --------------------

grants_router = APIRouter()


@grants_router.get("", response_model=Dict[str, Any])
async def list_delegation_grants(
    as_role: str = Query("investor", alias="as", pattern="^(investor|advisor)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Grants where the caller is the investor (default) or the advisor.

    Each row carries `is_usable` so the UI never has to re-derive expiry.
    """
    Advisor = aliased(User)
    Investor = aliased(User)

    column = (
        AssetDelegationGrant.investor_id if as_role == "investor"
        else AssetDelegationGrant.advisor_id
    )
    rows = (await db.execute(
        select(AssetDelegationGrant, Advisor, Investor)
        .join(Advisor, AssetDelegationGrant.advisor_id == Advisor.id)
        .join(Investor, AssetDelegationGrant.investor_id == Investor.id)
        .where(column == current_user.id)
        .order_by(AssetDelegationGrant.created_at.desc())
    )).all()

    now = datetime.now(timezone.utc)
    data = []
    for grant, advisor, investor in rows:
        item = serialize_grant(grant, advisor, investor)
        item["is_usable"] = grant_is_usable(grant, now)
        data.append(item)
    return {"success": True, "data": data}


@grants_router.post("/{grant_id}/lock", response_model=Dict[str, Any])
async def lock_delegation_grant(
    grant_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """"Confirm & lock" -- the investor accepts the asset the advisor entered.

    This is the second half of decision D1: the advisor kept EDIT after creating
    the asset so typos could be fixed without a fresh admin-approved request,
    and this call ends that window. The advisor keeps READ access to the asset
    via /advisor/clients/{id}/assets.
    """
    from app.models.notification import NotificationType
    from app.services.activity_service import log_activity
    from app.services.notification_service import NotificationService

    grant = (await db.execute(
        select(AssetDelegationGrant).where(AssetDelegationGrant.id == grant_id).with_for_update()
    )).scalar_one_or_none()
    if not grant:
        raise NotFoundException("AssetDelegationGrant", str(grant_id))

    is_owner = str(grant.investor_id) == str(current_user.id)
    if not (is_owner or current_user.role == Role.ADMIN):
        raise ForbiddenException(
            "Only the investor or an admin can confirm this asset.",
            code="CANNOT_LOCK_GRANT",
        )
    if grant.status != GrantStatus.CONSUMED.value:
        raise BadRequestException(
            f"Only an asset awaiting confirmation can be locked (this one is {grant.status})."
        )

    grant.status = GrantStatus.LOCKED.value
    await db.commit()
    await db.refresh(grant)

    await log_activity(
        db, current_user.id, grant.investor_id, "asset.confirmed_locked",
        entity_type="asset", entity_id=grant.asset_id,
        summary="Investor confirmed the asset; advisor edit access ended",
        meta={"grant_id": str(grant.id)},
    )
    await NotificationService.notify_user(
        db, grant.advisor_id, NotificationType.GENERAL, "Asset confirmed",
        "Your client confirmed the asset you added. It is now read-only for you.",
        None)

    logger.info(f"User {current_user.id} locked delegation grant {grant.id}")
    return {"success": True, "data": serialize_grant(grant)}


@grants_router.post("/{grant_id}/revoke", response_model=Dict[str, Any])
async def revoke_delegation_grant(
    grant_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Investor or admin withdraws an unconsumed authorisation."""
    from app.models.notification import NotificationType
    from app.services.notification_service import NotificationService

    grant = (await db.execute(
        select(AssetDelegationGrant).where(AssetDelegationGrant.id == grant_id).with_for_update()
    )).scalar_one_or_none()
    if not grant:
        raise NotFoundException("AssetDelegationGrant", str(grant_id))

    ensure_can_revoke_grant(grant, current_user)

    grant.status = GrantStatus.REVOKED.value
    grant.revoked_at = datetime.now(timezone.utc)
    grant.revoked_by = current_user.id
    await db.commit()
    await db.refresh(grant)

    await NotificationService.notify_user(
        db, grant.advisor_id, NotificationType.GENERAL, "Authorisation withdrawn",
        "An authorisation to create an asset on a client's behalf has been withdrawn.",
        None)

    logger.info(f"User {current_user.id} revoked delegation grant {grant.id}")
    return {"success": True, "data": serialize_grant(grant)}
