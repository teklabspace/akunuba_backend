from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import aliased
from typing import Dict, Any
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.kyc import KYCVerification
from app.models.advisor_client import AdvisorClient
from app.models.payment import Subscription
from app.core.permissions import Role
from app.core.exceptions import ForbiddenException, NotFoundException

router = APIRouter()

#: Error code the frontend branches on when an advisor reaches for a client that
#: is not theirs. Changing this string is a breaking API change.
NOT_YOUR_CLIENT = "NOT_YOUR_CLIENT"


def is_advisor_scope_allowed(user, assignment) -> bool:
    """May `user` read the data of the client `assignment` describes?

    Admins bypass the link entirely (platform oversight). An advisor needs an
    `advisor_clients` row naming them. Everyone else -- investors included --
    is denied, so an investor can never walk this path to another investor.
    """
    if user.role == Role.ADMIN:
        return True
    if user.role != Role.ADVISOR:
        return False
    if assignment is None:
        return False
    return str(assignment.advisor_id) == str(user.id)


async def ensure_advisor_of(db: AsyncSession, user: User, client_id) -> Account:
    """Authorise `user` for `client_id` and return that client's Account.

    Every client-scoped route below must call this FIRST. Assets, documents,
    goals and portfolio are all account-scoped, so returning the Account is what
    makes the rest of those endpoints uniform.
    """
    assignment = (await db.execute(
        select(AdvisorClient).where(AdvisorClient.client_id == client_id)
    )).scalar_one_or_none()

    if not is_advisor_scope_allowed(user, assignment):
        raise ForbiddenException(
            "This investor is not one of your clients.",
            # Literal, not the NOT_YOUR_CLIENT constant: the drift guard in
            # tests/test_error_code_drift.py only detects string literals at
            # raise sites, and a code it cannot see never reaches the contract.
            code="NOT_YOUR_CLIENT",
        )

    account = (await db.execute(
        select(Account).where(Account.user_id == client_id)
    )).scalar_one_or_none()
    if not account:
        raise NotFoundException("Account", str(client_id))
    return account


@router.get("/clients", response_model=Dict[str, Any])
async def list_my_clients(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The advisor's assigned investors (clients), with KYC status, plan, and the
    conversation_id of their auto-created chat."""
    if current_user.role not in (Role.ADVISOR, Role.ADMIN):
        raise ForbiddenException("Only advisors can view their client list.")

    from app.api.v1.subscriptions import get_plan_tier

    rows = (await db.execute(
        select(AdvisorClient, User)
        .join(User, AdvisorClient.client_id == User.id)
        .where(AdvisorClient.advisor_id == current_user.id)
        .order_by(AdvisorClient.created_at.desc())
    )).all()

    data = []
    for ac, client in rows:
        account = (await db.execute(
            select(Account).where(Account.user_id == client.id)
        )).scalar_one_or_none()

        kyc_status = None
        plan = None
        if account:
            kyc = (await db.execute(
                select(KYCVerification).where(KYCVerification.account_id == account.id)
            )).scalar_one_or_none()
            kyc_status = kyc.status.value if kyc else "not_started"
            sub = (await db.execute(
                select(Subscription).where(Subscription.account_id == account.id)
            )).scalar_one_or_none()
            plan = get_plan_tier(sub) if sub else None

        data.append({
            "client_id": str(client.id),
            "name": f"{client.first_name or ''} {client.last_name or ''}".strip() or client.email,
            "email": client.email,
            "kyc_status": kyc_status,
            "plan": plan,
            "conversation_id": str(ac.conversation_id) if ac.conversation_id else None,
        })

    return {"data": data, "total": len(data)}


@router.get("/book", response_model=Dict[str, Any])
async def my_book(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated portfolio view of the advisor's book for the dashboard
    charts: per-client totals with their asset-class split, plus the combined
    class allocation. Core (owned) assets only — same scope as
    /portfolio/allocation."""
    if current_user.role not in (Role.ADVISOR, Role.ADMIN):
        raise ForbiddenException("Only advisors can view their book.")

    from app.models.asset import Asset
    from app.services.net_worth import core_assets

    rows = (await db.execute(
        select(AdvisorClient, User)
        .join(User, AdvisorClient.client_id == User.id)
        .where(AdvisorClient.advisor_id == current_user.id)
        .order_by(AdvisorClient.created_at.desc())
    )).all()

    clients = []
    allocation_by_type: Dict[str, Dict[str, Any]] = {}
    book_total = 0.0

    for _, client in rows:
        account = (await db.execute(
            select(Account).where(Account.user_id == client.id)
        )).scalar_one_or_none()

        class_values: Dict[str, float] = {}
        if account:
            assets = core_assets((await db.execute(
                select(Asset).where(Asset.account_id == account.id)
            )).scalars().all())
            for asset in assets:
                asset_type = asset.asset_type.value if asset.asset_type else "other"
                value = float(asset.current_value or 0)
                class_values[asset_type] = class_values.get(asset_type, 0.0) + value
                bucket = allocation_by_type.setdefault(
                    asset_type, {"value": 0.0, "count": 0}
                )
                bucket["value"] += value
                bucket["count"] += 1

        client_total = sum(class_values.values())
        book_total += client_total
        clients.append({
            "client_id": str(client.id),
            "name": f"{client.first_name or ''} {client.last_name or ''}".strip() or client.email,
            "total_value": client_total,
            "classes": [
                {"asset_type": t, "value": v}
                for t, v in sorted(class_values.items(), key=lambda kv: -kv[1])
            ],
        })

    clients.sort(key=lambda c: -c["total_value"])
    allocation = [
        {"asset_type": t, "value": d["value"], "count": d["count"]}
        for t, d in sorted(allocation_by_type.items(), key=lambda kv: -kv[1]["value"])
    ]
    return {
        "data": {
            "total_value": book_total,
            "client_count": len(clients),
            "clients": clients,
            "allocation": allocation,
        }
    }


# -- Client-scoped read access (gap-analysis #4) ------------------------------
# Every route here calls ensure_advisor_of() FIRST and logs the access, because
# in wealth management "who looked at this client's data" is itself the
# audit-relevant event.

def _client_person(u: User) -> Dict[str, Any]:
    name = f"{u.first_name or ''} {u.last_name or ''}".strip()
    return {"id": str(u.id), "name": name or u.email, "email": u.email, "phone": u.phone}


async def _load_client(db: AsyncSession, client_id) -> User:
    client = (await db.execute(select(User).where(User.id == client_id))).scalar_one_or_none()
    if not client:
        raise NotFoundException("User", str(client_id))
    return client


@router.get("/clients/{client_id}", response_model=Dict[str, Any])
async def get_client_overview(
    client_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Profile, KYC, plan, net worth and asset-class allocation for one client."""
    from app.api.v1.subscriptions import get_plan_tier
    from app.models.asset import Asset
    from app.services.activity_service import log_activity
    from app.services.net_worth import core_assets

    account = await ensure_advisor_of(db, current_user, client_id)
    client = await _load_client(db, client_id)

    kyc = (await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )).scalar_one_or_none()
    sub = (await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )).scalar_one_or_none()

    assets = core_assets((await db.execute(
        select(Asset).where(Asset.account_id == account.id)
    )).scalars().all())

    by_type: Dict[str, float] = {}
    for a in assets:
        t = a.asset_type.value if a.asset_type else "other"
        by_type[t] = by_type.get(t, 0.0) + float(a.current_value or 0)

    await log_activity(
        db, current_user.id, client_id, "client.viewed",
        summary=f"Viewed client overview for {_client_person(client)['name']}",
    )

    # The auto-created advisor<->investor chat. Surfaced so an admin reviewing
    # the relationship can read the transcript without a second lookup.
    assignment = (await db.execute(
        select(AdvisorClient).where(AdvisorClient.client_id == client_id)
    )).scalar_one_or_none()

    return {
        "success": True,
        "data": {
            "client": _client_person(client),
            "advisor_id": str(assignment.advisor_id) if assignment else None,
            "conversation_id": (
                str(assignment.conversation_id)
                if assignment and assignment.conversation_id else None
            ),
            "kyc_status": kyc.status.value if kyc else "not_started",
            "plan": get_plan_tier(sub) if sub else None,
            "net_worth": sum(by_type.values()),
            "asset_count": len(assets),
            "allocation": [
                {"asset_type": t, "value": v}
                for t, v in sorted(by_type.items(), key=lambda kv: -kv[1])
            ],
        },
    }


@router.get("/clients/{client_id}/assets", response_model=Dict[str, Any])
async def get_client_assets(
    client_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The client's assets (read-only list)."""
    from app.models.asset import Asset
    from app.services.activity_service import log_activity

    account = await ensure_advisor_of(db, current_user, client_id)
    rows = (await db.execute(
        select(Asset).where(Asset.account_id == account.id).order_by(Asset.created_at.desc())
    )).scalars().all()

    await log_activity(db, current_user.id, client_id, "client.assets.viewed",
                       summary=f"Viewed {len(rows)} client asset(s)")

    return {
        "success": True,
        "data": [{
            "id": str(a.id),
            "asset_code": a.asset_code,
            "name": a.name,
            "asset_type": a.asset_type.value if a.asset_type else None,
            "category_group": a.category_group.value if a.category_group else None,
            "current_value": float(a.current_value or 0),
            "status": a.status.value if a.status else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        } for a in rows],
        "total": len(rows),
    }


@router.get("/clients/{client_id}/documents", response_model=Dict[str, Any])
async def get_client_documents(
    client_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The client's documents — metadata only.

    Deliberately no file_path / storage path: this grants an advisor the ability
    to SEE that a document exists, not to pull its bytes. Download-on-behalf is a
    separate decision with its own consent question.
    """
    from app.models.document import Document
    from app.services.activity_service import log_activity

    account = await ensure_advisor_of(db, current_user, client_id)
    rows = (await db.execute(
        select(Document).where(Document.account_id == account.id)
        .order_by(Document.created_at.desc())
    )).scalars().all()

    await log_activity(db, current_user.id, client_id, "client.documents.viewed",
                       summary=f"Viewed {len(rows)} client document(s)")

    return {
        "success": True,
        "data": [{
            "id": str(d.id),
            "file_name": d.file_name,
            "document_type": d.document_type.value if d.document_type else None,
            "file_size": d.file_size,
            "mime_type": d.mime_type,
            "description": d.description,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        } for d in rows],
        "total": len(rows),
    }


@router.get("/clients/{client_id}/goals", response_model=Dict[str, Any])
async def get_client_goals(
    client_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The client's financial goals with progress."""
    from app.models.investment_goal import InvestmentGoal
    from app.services.activity_service import log_activity

    account = await ensure_advisor_of(db, current_user, client_id)
    rows = (await db.execute(
        select(InvestmentGoal).where(InvestmentGoal.account_id == account.id)
        .order_by(InvestmentGoal.created_at.desc())
    )).scalars().all()

    await log_activity(db, current_user.id, client_id, "client.goals.viewed",
                       summary=f"Viewed {len(rows)} client goal(s)")

    data = []
    for g in rows:
        target = float(g.target_amount or 0)
        current = float(g.current_value or 0)
        data.append({
            "id": str(g.id),
            "name": g.name,
            "symbol": g.symbol,
            "target_amount": target,
            "current_value": current,
            "progress_pct": round((current / target) * 100, 2) if target else 0.0,
            "monthly_contribution": float(g.monthly_contribution) if g.monthly_contribution else None,
            "risk_tolerance": g.risk_tolerance,
            "status": g.status.value if g.status else None,
            "target_date": g.target_date.isoformat() if g.target_date else None,
        })
    return {"success": True, "data": data, "total": len(data)}


@router.get("/clients/{client_id}/requests", response_model=Dict[str, Any])
async def get_client_requests(
    client_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The client's appraisal and sale requests, newest first."""
    from app.models.asset import Asset, AssetAppraisal, AssetSaleRequest
    from app.services.activity_service import log_activity

    account = await ensure_advisor_of(db, current_user, client_id)

    appraisals = (await db.execute(
        select(AssetAppraisal, Asset)
        .join(Asset, AssetAppraisal.asset_id == Asset.id)
        .where(Asset.account_id == account.id)
        .order_by(AssetAppraisal.created_at.desc())
    )).all()

    sales = (await db.execute(
        select(AssetSaleRequest, Asset)
        .join(Asset, AssetSaleRequest.asset_id == Asset.id)
        .where(Asset.account_id == account.id)
        .order_by(AssetSaleRequest.created_at.desc())
    )).all()

    data = [{
        "id": str(ap.id),
        "kind": "appraisal",
        "asset_id": str(asset.id),
        "asset_name": asset.name,
        "status": ap.status.value if ap.status else None,
        "appraisal_type": ap.appraisal_type.value if ap.appraisal_type else None,
        "estimated_value": float(ap.estimated_value) if ap.estimated_value else None,
        "created_at": ap.created_at.isoformat() if ap.created_at else None,
    } for ap, asset in appraisals] + [{
        "id": str(sr.id),
        "kind": "sale_request",
        "asset_id": str(asset.id),
        "asset_name": asset.name,
        "status": sr.status.value if sr.status else None,
        "target_price": float(sr.target_price) if sr.target_price else None,
        "created_at": sr.created_at.isoformat() if sr.created_at else None,
    } for sr, asset in sales]

    data.sort(key=lambda r: r["created_at"] or "", reverse=True)

    await log_activity(db, current_user.id, client_id, "client.requests.viewed",
                       summary=f"Viewed {len(data)} client request(s)")

    return {"success": True, "data": data, "total": len(data)}


@router.get("/clients/{client_id}/activity", response_model=Dict[str, Any])
async def get_client_activity(
    client_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activity history for this client — who did what, when.

    Reading the log is NOT itself logged; otherwise opening the audit tab would
    permanently pollute the record it is showing.
    """
    from app.models.activity import ActivityLog

    await ensure_advisor_of(db, current_user, client_id)

    Actor = aliased(User)
    rows = (await db.execute(
        select(ActivityLog, Actor)
        .outerjoin(Actor, ActivityLog.actor_id == Actor.id)
        .where(ActivityLog.subject_user_id == client_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )).all()

    return {
        "success": True,
        "data": [{
            "id": str(log.id),
            "action": log.action,
            "summary": log.summary,
            "entity_type": log.entity_type,
            "entity_id": str(log.entity_id) if log.entity_id else None,
            "actor": _client_person(actor) if actor else None,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        } for log, actor in rows],
        "total": len(rows),
    }
