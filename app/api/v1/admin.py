from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User, Role
from app.models.account import Account, AccountType
from app.models.payment import Subscription, SubscriptionStatus, SubscriptionPlan
from app.models.kyc import KYCVerification, KYCStatus, KYCDocument, KYCCaptureStatus
from app.models.kyb import KYBVerification, KYBStatus
from app.models.marketplace import MarketplaceListing, ListingStatus, EscrowTransaction, EscrowStatus
from app.models.support import SupportTicket, TicketStatus
from app.models.asset import Asset, AssetPhoto
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException, ConflictException
from app.core.permissions import Permission, has_permission
from app.core.security import get_password_hash, generate_reset_token
from app.services.email_service import EmailService
from app.config import settings
from app.utils.logger import logger
from uuid import UUID
import secrets
import json
from pydantic import BaseModel, EmailStr

router = APIRouter()


def require_admin(current_user: User = Depends(get_current_user)):
    """Dependency to require admin role"""
    if current_user.role != Role.ADMIN:
        raise ForbiddenException("Admin access required")
    return current_user


class AdminDashboardResponse(BaseModel):
    users: Dict[str, int]
    accounts: Dict[str, int]
    subscriptions: Dict[str, int]
    kyc_queue: int
    kyb_queue: int
    pending_listings: int
    open_tickets: int
    active_escrows: int
    disputes: int
    revenue: Dict[str, float]


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_admin_dashboard(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get admin dashboard statistics"""
    from app.models.payment import Payment, PaymentStatus
    
    # User statistics
    total_users_result = await db.execute(select(func.count(User.id)))
    total_users = total_users_result.scalar() or 0
    
    active_users_result = await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )
    active_users = active_users_result.scalar() or 0
    
    verified_users_result = await db.execute(
        select(func.count(User.id)).where(User.is_verified == True)
    )
    verified_users = verified_users_result.scalar() or 0
    
    # Account statistics
    total_accounts_result = await db.execute(select(func.count(Account.id)))
    total_accounts = total_accounts_result.scalar() or 0
    
    individual_accounts_result = await db.execute(
        select(func.count(Account.id)).where(Account.account_type == AccountType.INDIVIDUAL)
    )
    individual_accounts = individual_accounts_result.scalar() or 0
    
    corporate_accounts_result = await db.execute(
        select(func.count(Account.id)).where(Account.account_type == AccountType.CORPORATE)
    )
    corporate_accounts = corporate_accounts_result.scalar() or 0
    
    trust_accounts_result = await db.execute(
        select(func.count(Account.id)).where(Account.account_type == AccountType.TRUST)
    )
    trust_accounts = trust_accounts_result.scalar() or 0
    
    # Subscription statistics
    total_subscriptions_result = await db.execute(select(func.count(Subscription.id)))
    total_subscriptions = total_subscriptions_result.scalar() or 0
    
    active_subscriptions_result = await db.execute(
        select(func.count(Subscription.id)).where(Subscription.status == SubscriptionStatus.ACTIVE)
    )
    active_subscriptions = active_subscriptions_result.scalar() or 0
    
    # KYC/KYB queue
    pending_kyc_result = await db.execute(
        select(func.count(KYCVerification.id)).where(
            KYCVerification.status.in_([KYCStatus.IN_PROGRESS, KYCStatus.PENDING_REVIEW])
        )
    )
    pending_kyc = pending_kyc_result.scalar() or 0
    
    pending_kyb_result = await db.execute(
        select(func.count(KYBVerification.id)).where(
            KYBVerification.status.in_([KYBStatus.IN_PROGRESS, KYBStatus.PENDING_REVIEW])
        )
    )
    pending_kyb = pending_kyb_result.scalar() or 0
    
    # Marketplace statistics
    pending_listings_result = await db.execute(
        select(func.count(MarketplaceListing.id)).where(
            MarketplaceListing.status == ListingStatus.PENDING_APPROVAL
        )
    )
    pending_listings = pending_listings_result.scalar() or 0
    
    # Support statistics
    open_tickets_result = await db.execute(
        select(func.count(SupportTicket.id)).where(
            SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS])
        )
    )
    open_tickets = open_tickets_result.scalar() or 0
    
    # Escrow statistics
    active_escrows_result = await db.execute(
        select(func.count(EscrowTransaction.id)).where(
            EscrowTransaction.status.in_([EscrowStatus.PENDING, EscrowStatus.FUNDED])
        )
    )
    active_escrows = active_escrows_result.scalar() or 0
    
    disputes_result = await db.execute(
        select(func.count(EscrowTransaction.id)).where(
            EscrowTransaction.status == EscrowStatus.DISPUTED
        )
    )
    disputes = disputes_result.scalar() or 0
    
    # Revenue statistics
    total_revenue_result = await db.execute(
        select(func.sum(Payment.amount)).where(Payment.status == PaymentStatus.COMPLETED)
    )
    total_revenue = float(total_revenue_result.scalar() or 0)
    
    monthly_revenue_result = await db.execute(
        select(func.sum(Payment.amount)).where(
            Payment.status == PaymentStatus.COMPLETED,
            Payment.created_at >= datetime.utcnow() - timedelta(days=30)
        )
    )
    monthly_revenue = float(monthly_revenue_result.scalar() or 0)
    
    return AdminDashboardResponse(
        users={
            "total": total_users,
            "active": active_users,
            "verified": verified_users
        },
        accounts={
            "total": total_accounts,
            "individual": individual_accounts,
            "corporate": corporate_accounts,
            "trust": trust_accounts
        },
        subscriptions={
            "total": total_subscriptions,
            "active": active_subscriptions
        },
        kyc_queue=pending_kyc,
        kyb_queue=pending_kyb,
        pending_listings=pending_listings,
        open_tickets=open_tickets,
        active_escrows=active_escrows,
        disputes=disputes,
        revenue={
            "total": total_revenue,
            "monthly": monthly_revenue
        }
    )


@router.get("/disputes")
async def list_disputes(
    status_filter: Optional[EscrowStatus] = Query(None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """List all escrow disputes"""
    query = select(EscrowTransaction).where(EscrowTransaction.status == EscrowStatus.DISPUTED)
    
    if status_filter:
        query = query.where(EscrowTransaction.status == status_filter)
    
    result = await db.execute(query.order_by(EscrowTransaction.created_at.desc()))
    disputes = result.scalars().all()
    
    return [
        {
            "id": str(dispute.id),
            "listing_id": str(dispute.listing_id),
            "buyer_id": str(dispute.buyer_id),
            "seller_id": str(dispute.seller_id),
            "amount": float(dispute.amount),
            "status": dispute.status.value,
            "created_at": dispute.created_at.isoformat()
        }
        for dispute in disputes
    ]


@router.get("/disputes/{dispute_id}")
async def get_dispute(
    dispute_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get dispute details"""
    result = await db.execute(
        select(EscrowTransaction).where(EscrowTransaction.id == dispute_id)
    )
    dispute = result.scalar_one_or_none()
    
    if not dispute:
        raise NotFoundException("Dispute", str(dispute_id))
    
    return {
        "id": str(dispute.id),
        "listing_id": str(dispute.listing_id),
        "offer_id": str(dispute.offer_id),
        "buyer_id": str(dispute.buyer_id),
        "seller_id": str(dispute.seller_id),
        "amount": float(dispute.amount),
        "commission": float(dispute.commission) if dispute.commission else None,
        "status": dispute.status.value,
        "created_at": dispute.created_at.isoformat(),
        "released_at": dispute.released_at.isoformat() if dispute.released_at else None
    }


class ResolveDisputeRequest(BaseModel):
    resolution: str  # "release" or "refund"
    reason: Optional[str] = None


@router.post("/disputes/{dispute_id}/resolve")
async def resolve_dispute(
    dispute_id: UUID,
    resolution_data: ResolveDisputeRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Resolve an escrow dispute"""
    from app.integrations.stripe_client import StripeClient
    
    result = await db.execute(
        select(EscrowTransaction).where(EscrowTransaction.id == dispute_id)
    )
    dispute = result.scalar_one_or_none()
    
    if not dispute:
        raise NotFoundException("Dispute", str(dispute_id))
    
    if dispute.status != EscrowStatus.DISPUTED:
        raise BadRequestException("Dispute is not in disputed status")
    
    if resolution_data.resolution == "release":
        # Release funds to seller
        if dispute.stripe_payment_intent_id:
            try:
                StripeClient.release_payment(dispute.stripe_payment_intent_id)
            except Exception as e:
                logger.error(f"Failed to release payment: {e}")
        
        dispute.status = EscrowStatus.RELEASED
        dispute.released_at = datetime.utcnow()
        
        # Notify seller
        from app.services.notification_service import NotificationService, NotificationType
        await NotificationService.create_notification(
            db=db,
            account_id=dispute.seller_id,
            notification_type=NotificationType.PAYMENT_RECEIVED,
            title="Dispute Resolved - Funds Released",
            message=f"Dispute resolved in your favor. Funds have been released."
        )
        
    elif resolution_data.resolution == "refund":
        # Refund to buyer
        if dispute.stripe_payment_intent_id:
            try:
                StripeClient.create_refund(
                    payment_intent_id=dispute.stripe_payment_intent_id,
                    amount=int(dispute.amount * 100)  # Convert to cents
                )
            except Exception as e:
                logger.error(f"Failed to create refund: {e}")
        
        dispute.status = EscrowStatus.REFUNDED
        
        # Notify buyer
        from app.services.notification_service import NotificationService, NotificationType
        await NotificationService.create_notification(
            db=db,
            account_id=dispute.buyer_id,
            notification_type=NotificationType.PAYMENT_RECEIVED,
            title="Dispute Resolved - Refund Issued",
            message=f"Dispute resolved. Refund has been issued to your payment method."
        )
    
    await db.commit()
    await db.refresh(dispute)
    
    logger.info(f"Dispute {dispute_id} resolved by admin {current_user.id}")
    return {"message": f"Dispute resolved: {resolution_data.resolution}", "dispute": dispute}


# ==================== ESCROW OVERSIGHT ====================
# /admin/disputes only surfaces DISPUTED escrows. These give admins visibility of
# EVERY escrow (pending/funded/released/refunded/disputed) with all its ids and
# both parties, so the admin UI can show the same escrow_id the buyer/seller see.

async def _escrow_party_lookup(db: AsyncSession, account_ids: set) -> Dict[UUID, Dict[str, Any]]:
    """Batch-resolve account_id -> {account_name, user_email} for buyers/sellers,
    so the admin escrow views show who is involved instead of bare UUIDs."""
    if not account_ids:
        return {}
    rows = (await db.execute(
        select(Account.id, Account.account_name, User.email)
        .join(User, User.id == Account.user_id)
        .where(Account.id.in_(account_ids))
    )).all()
    return {
        acc_id: {"account_name": name, "user_email": email}
        for acc_id, name, email in rows
    }


async def _escrow_listing_lookup(db: AsyncSession, listing_ids: set) -> Dict[UUID, Dict[str, Any]]:
    """Batch-resolve listing_id -> {title, asset_name, thumbnail_url} so the admin
    escrow table (and investor 'Manage Escrow' card) can render the item without a
    second call. Thumbnail prefers the asset's primary photo, else its first."""
    if not listing_ids:
        return {}
    listings = (await db.execute(
        select(MarketplaceListing.id, MarketplaceListing.title, MarketplaceListing.asset_id)
        .where(MarketplaceListing.id.in_(listing_ids))
    )).all()

    asset_ids = {asset_id for _, _, asset_id in listings if asset_id}
    asset_names: Dict[UUID, str] = {}
    thumbnails: Dict[UUID, str] = {}
    if asset_ids:
        asset_names = {
            aid: name
            for aid, name in (await db.execute(
                select(Asset.id, Asset.name).where(Asset.id.in_(asset_ids))
            )).all()
        }
        # One row per asset: primary photo first, else earliest, wins.
        photo_rows = (await db.execute(
            select(AssetPhoto.asset_id, AssetPhoto.url, AssetPhoto.is_primary)
            .where(AssetPhoto.asset_id.in_(asset_ids))
            .order_by(AssetPhoto.is_primary.desc(), AssetPhoto.created_at.asc())
        )).all()
        for aid, url, _is_primary in photo_rows:
            thumbnails.setdefault(aid, url)  # first row per asset (primary or earliest)

    result: Dict[UUID, Dict[str, Any]] = {}
    for lid, title, asset_id in listings:
        result[lid] = {
            "title": title,
            "asset_name": asset_names.get(asset_id),
            "thumbnail_url": thumbnails.get(asset_id),
        }
    return result


def _admin_escrow_item(
    escrow: EscrowTransaction,
    parties: Dict[UUID, Dict[str, Any]],
    listings: Dict[UUID, Dict[str, Any]],
) -> Dict[str, Any]:
    buyer = parties.get(escrow.buyer_id, {})
    seller = parties.get(escrow.seller_id, {})
    listing = listings.get(escrow.listing_id, {})
    return {
        "id": str(escrow.id),
        "listing_id": str(escrow.listing_id),
        "offer_id": str(escrow.offer_id),
        "listing_title": listing.get("title"),
        "asset_name": listing.get("asset_name"),
        "thumbnail_url": listing.get("thumbnail_url"),
        "status": escrow.status.value if hasattr(escrow.status, "value") else str(escrow.status),
        "amount": float(escrow.amount),
        "commission": float(escrow.commission) if escrow.commission is not None else None,
        "currency": escrow.currency,
        "stripe_payment_intent_id": escrow.stripe_payment_intent_id,
        "buyer": {
            "account_id": str(escrow.buyer_id),
            "account_name": buyer.get("account_name"),
            "email": buyer.get("user_email"),
        },
        "seller": {
            "account_id": str(escrow.seller_id),
            "account_name": seller.get("account_name"),
            "email": seller.get("user_email"),
        },
        "resolved_by": str(escrow.resolved_by) if escrow.resolved_by else None,
        "resolution_reason": escrow.resolution_reason,
        "created_at": escrow.created_at.isoformat() if escrow.created_at else None,
        "released_at": escrow.released_at.isoformat() if escrow.released_at else None,
    }


@router.get("/escrow", response_model=Dict[str, Any])
async def list_escrows(
    status_filter: Optional[EscrowStatus] = Query(None, description="Filter by escrow status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List ALL escrow transactions (admin oversight), newest first, paginated."""
    base = select(EscrowTransaction)
    count_q = select(func.count(EscrowTransaction.id))
    if status_filter:
        base = base.where(EscrowTransaction.status == status_filter)
        count_q = count_q.where(EscrowTransaction.status == status_filter)

    total = (await db.execute(count_q)).scalar() or 0
    rows = (await db.execute(
        base.order_by(EscrowTransaction.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )).scalars().all()

    party_ids = {e.buyer_id for e in rows} | {e.seller_id for e in rows}
    parties = await _escrow_party_lookup(db, party_ids)
    listings = await _escrow_listing_lookup(db, {e.listing_id for e in rows})

    return {
        "items": [_admin_escrow_item(e, parties, listings) for e in rows],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit else 0,
    }


@router.get("/escrow/{escrow_id}", response_model=Dict[str, Any])
async def get_escrow_admin(
    escrow_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Full detail for a single escrow (admin oversight), including both parties."""
    escrow = (await db.execute(
        select(EscrowTransaction).where(EscrowTransaction.id == escrow_id)
    )).scalar_one_or_none()
    if not escrow:
        raise NotFoundException("Escrow", str(escrow_id))
    parties = await _escrow_party_lookup(db, {escrow.buyer_id, escrow.seller_id})
    listings = await _escrow_listing_lookup(db, {escrow.listing_id})
    return _admin_escrow_item(escrow, parties, listings)


class EscrowActionRequest(BaseModel):
    reason: Optional[str] = None


# Admin may force-resolve only from these live states. Terminal states
# (released/refunded) are rejected → guarantees idempotency (no double pay/refund).
_RESOLVABLE_ESCROW_STATES = (EscrowStatus.FUNDED, EscrowStatus.DISPUTED)


async def _refund_escrow_via_stripe(escrow: EscrowTransaction) -> None:
    """Best-effort Stripe refund to the buyer. create_refund takes a CHARGE id, so
    resolve PaymentIntent -> latest charge -> refund (mirrors marketplace.refund_escrow).
    Logged, not raised — the DB transition is the source of truth and must not be
    blocked by a Stripe hiccup."""
    if not escrow.stripe_payment_intent_id:
        return
    try:
        import stripe
        from app.integrations.stripe_client import StripeClient
        payment_intent = stripe.PaymentIntent.retrieve(escrow.stripe_payment_intent_id)
        charges = getattr(payment_intent, "charges", None)
        if charges and charges.data:
            StripeClient.create_refund(charges.data[0].id, amount=int(escrow.amount * 100))
    except Exception as e:
        logger.error(f"Stripe refund failed for escrow {escrow.id}: {e}")


async def _notify_escrow_parties(db: AsyncSession, escrow: EscrowTransaction, title: str, message: str) -> None:
    """Notify BOTH buyer and seller of an admin escrow action (best-effort)."""
    from app.services.notification_service import NotificationService
    from app.models.notification import NotificationType
    for account_id in {escrow.buyer_id, escrow.seller_id}:
        try:
            await NotificationService.create_notification(
                db=db,
                account_id=account_id,
                notification_type=NotificationType.PAYMENT_RECEIVED,
                title=title,
                message=message,
                send_email=False,
            )
        except Exception as e:
            logger.error(f"Failed to notify {account_id} for escrow {escrow.id}: {e}")


async def _admin_escrow_response(db: AsyncSession, escrow: EscrowTransaction) -> Dict[str, Any]:
    parties = await _escrow_party_lookup(db, {escrow.buyer_id, escrow.seller_id})
    listings = await _escrow_listing_lookup(db, {escrow.listing_id})
    return _admin_escrow_item(escrow, parties, listings)


@router.post("/escrow/{escrow_id}/release", response_model=Dict[str, Any])
async def admin_release_escrow(
    escrow_id: UUID,
    body: Optional[EscrowActionRequest] = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin force-release a funded/disputed escrow to the seller.

    Idempotent: an already released/refunded escrow returns 400 INVALID_ESCROW_STATE
    (no double action). Persists the acting admin + reason for audit.
    """
    escrow = (await db.execute(
        select(EscrowTransaction).where(EscrowTransaction.id == escrow_id)
    )).scalar_one_or_none()
    if not escrow:
        raise NotFoundException("Escrow", str(escrow_id))
    if escrow.status not in _RESOLVABLE_ESCROW_STATES:
        raise BadRequestException(
            f"Cannot release escrow in '{escrow.status.value}' state; must be funded or disputed.",
            code="INVALID_ESCROW_STATE",
        )

    reason = body.reason if body else None
    # Release is a status transition in this system (funds were captured at fund
    # time; seller payout via Stripe Connect is not wired here — see resolve_dispute).
    escrow.status = EscrowStatus.RELEASED
    escrow.released_at = datetime.utcnow()
    escrow.resolved_by = current_user.id
    escrow.resolution_reason = reason
    await db.commit()
    await db.refresh(escrow)

    await _notify_escrow_parties(
        db, escrow,
        "Escrow released",
        "An administrator released this escrow; funds are released to the seller."
        + (f" Reason: {reason}" if reason else ""),
    )
    logger.info(f"Admin {current_user.id} released escrow {escrow_id} (reason={reason!r})")
    return await _admin_escrow_response(db, escrow)


@router.post("/escrow/{escrow_id}/refund", response_model=Dict[str, Any])
async def admin_refund_escrow(
    escrow_id: UUID,
    body: Optional[EscrowActionRequest] = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin force-refund a funded/disputed escrow to the buyer (Stripe refund).

    Idempotent: an already released/refunded escrow returns 400 INVALID_ESCROW_STATE
    (no double refund). Persists the acting admin + reason for audit.
    """
    escrow = (await db.execute(
        select(EscrowTransaction).where(EscrowTransaction.id == escrow_id)
    )).scalar_one_or_none()
    if not escrow:
        raise NotFoundException("Escrow", str(escrow_id))
    if escrow.status not in _RESOLVABLE_ESCROW_STATES:
        raise BadRequestException(
            f"Cannot refund escrow in '{escrow.status.value}' state; must be funded or disputed.",
            code="INVALID_ESCROW_STATE",
        )

    reason = body.reason if body else None
    # Refund via Stripe BEFORE flipping state so a hard failure is visible; the
    # state guard above prevents a second call once we reach 'refunded'.
    await _refund_escrow_via_stripe(escrow)
    escrow.status = EscrowStatus.REFUNDED
    escrow.resolved_by = current_user.id
    escrow.resolution_reason = reason
    await db.commit()
    await db.refresh(escrow)

    await _notify_escrow_parties(
        db, escrow,
        "Escrow refunded",
        "An administrator refunded this escrow; funds are returned to the buyer."
        + (f" Reason: {reason}" if reason else ""),
    )
    logger.info(f"Admin {current_user.id} refunded escrow {escrow_id} (reason={reason!r})")
    return await _admin_escrow_response(db, escrow)


# ==================== USER MANAGEMENT ====================

class UserListItem(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    phone: Optional[str]
    role: str
    is_active: bool
    is_verified: bool
    created_at: Optional[datetime]
    last_login: Optional[datetime]

    class Config:
        from_attributes = True


class UserDetailResponse(UserListItem):
    account_id: Optional[UUID]
    account_type: Optional[str]
    subscription_plan: Optional[str]
    kyc_status: Optional[str]
    two_factor_auth_enabled: bool


class RoleUpdateRequest(BaseModel):
    role: Role


class CreateUserRequest(BaseModel):
    """Admin-created staff user. Only advisors can be created here — new admins are
    made by promoting an existing user via PATCH /admin/users/{id}/role."""
    email: EmailStr
    first_name: str
    last_name: str
    phone: Optional[str] = None
    # Role is assigned by the backend (always "advisor"); the frontend should OMIT
    # this field. It is accepted only for backward/explicit callers and, if sent,
    # must equal "advisor" — any other value is rejected with ROLE_NOT_ALLOWED.
    role: Optional[str] = "advisor"
    # Password mode (admin's choice):
    #   - provide `password`        -> admin sets the initial password; advisor can
    #                                  log in immediately (no invite email sent).
    #   - omit `password` (default) -> advisor is emailed a set-password invite link.
    password: Optional[str] = None


@router.post("/users", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create an advisor account — admin only.

    The advisor is created pre-verified (no OTP). Password handling is the admin's
    choice: if ``password`` is provided the admin sets it directly and the advisor
    can log in immediately; otherwise the advisor is emailed a set-password invite
    link (reuses the password-reset token flow). Investors must self-register;
    admins are made by role promotion.
    """
    # Enforce advisor-only creation.
    requested_role = (body.role or "advisor").strip().lower()
    if requested_role != "advisor":
        raise BadRequestException(
            "Only advisors can be created here. Promote an existing user to admin "
            "via PATCH /admin/users/{id}/role.",
            code="ROLE_NOT_ALLOWED",
        )

    # Reject duplicate email.
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise ConflictException("A user with this email already exists.")

    now = datetime.now(timezone.utc)
    chosen_password = (body.password or "").strip()
    invite_token: Optional[str] = None

    if chosen_password:
        # Mode A: admin sets the password — advisor can log in right away.
        if len(chosen_password) < 8:
            raise BadRequestException(
                "Password must be at least 8 characters.", code="VALIDATION_ERROR"
            )
        hashed_password = get_password_hash(chosen_password)
        reset_token = None
        reset_expires = None
    else:
        # Mode B: no password — store an unusable random hash and email an invite
        # link so the advisor sets their own password.
        hashed_password = get_password_hash(secrets.token_urlsafe(32))
        invite_token = generate_reset_token()
        reset_token = invite_token
        reset_expires = now + timedelta(days=7)

    user = User(
        email=body.email,
        hashed_password=hashed_password,
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        role=Role.ADVISOR,
        is_active=True,
        # Pre-verified: advisor skips the OTP/email-verification step entirely.
        is_verified=True,
        email_verified_at=now,
        password_reset_token=reset_token,
        password_reset_expires_at=reset_expires,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    email_sent = False
    if invite_token:
        invite_name = f"{body.first_name or ''} {body.last_name or ''}".strip() or "there"
        email_sent = await EmailService.send_advisor_invite_email(
            to_email=user.email,
            to_name=invite_name,
            invite_token=invite_token,
        )
        if not email_sent:
            logger.error(f"Advisor invite email failed to send for {user.email}")

    logger.info(
        f"Admin {current_user.id} created advisor {user.id} ({user.email}); "
        f"password_set={bool(chosen_password)}"
    )

    data = {
        "id": str(user.id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role.value,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "password_set": bool(chosen_password),
        "invite_email_sent": email_sent,
    }
    # Surface the invite link in development to ease testing (mirrors /auth/register).
    if settings.APP_ENV == "development" and invite_token:
        data["invite_token"] = invite_token

    message = (
        "Advisor created with the password you set. They can log in now."
        if chosen_password
        else "Advisor created. An invitation to set their password has been emailed."
    )
    return {"message": message, "data": data}


@router.get("/users", response_model=Dict[str, Any])
async def list_users(
    search: Optional[str] = Query(None, description="Search by name or email"),
    role: Optional[Role] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    is_verified: Optional[bool] = Query(None, description="Filter by verified status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all users — admin only"""
    from sqlalchemy import or_, asc

    query = select(User)
    count_query = select(func.count(User.id))

    if search:
        filter_expr = or_(
            User.email.ilike(f"%{search}%"),
            User.first_name.ilike(f"%{search}%"),
            User.last_name.ilike(f"%{search}%"),
        )
        query = query.where(filter_expr)
        count_query = count_query.where(filter_expr)

    if role is not None:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)

    if is_active is not None:
        query = query.where(User.is_active == is_active)
        count_query = count_query.where(User.is_active == is_active)

    if is_verified is not None:
        query = query.where(User.is_verified == is_verified)
        count_query = count_query.where(User.is_verified == is_verified)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await db.execute(
        query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
    )
    users = result.scalars().all()

    return {
        "data": [
            {
                "id": str(u.id),
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "phone": u.phone,
                "role": u.role.value,
                "is_active": u.is_active,
                "is_verified": u.is_verified,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login": u.last_login.isoformat() if u.last_login else None,
            }
            for u in users
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        },
    }


@router.get("/users/{user_id}", response_model=Dict[str, Any])
async def get_user_detail(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get full details for a single user — admin only"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", str(user_id))

    # Account info
    account_result = await db.execute(
        select(Account).where(Account.user_id == user_id)
    )
    account = account_result.scalar_one_or_none()

    # Subscription info — report the real product tier, not the legacy enum.
    subscription_plan = None
    if account:
        from app.api.v1.subscriptions import get_plan_tier
        sub_result = await db.execute(
            select(Subscription).where(
                Subscription.account_id == account.id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
        sub = sub_result.scalar_one_or_none()
        subscription_plan = get_plan_tier(sub) if sub else None

    # KYC status
    kyc_status = None
    if account:
        kyc_result = await db.execute(
            select(KYCVerification).where(KYCVerification.account_id == account.id)
        )
        kyc = kyc_result.scalar_one_or_none()
        kyc_status = kyc.status.value if kyc else None

    return {
        "data": {
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone": user.phone,
            "role": user.role.value,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "two_factor_auth_enabled": user.two_factor_auth_enabled,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "account_id": str(account.id) if account else None,
            "account_type": account.account_type.value if account else None,
            "subscription_plan": subscription_plan,
            "kyc_status": kyc_status,
        }
    }


@router.patch("/users/{user_id}/role", response_model=Dict[str, Any])
async def update_user_role(
    user_id: UUID,
    body: RoleUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's role — admin only.
    Accepts role: 'investor' | 'advisor' | 'admin'
    """
    if user_id == current_user.id:
        raise BadRequestException("You cannot change your own role")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", str(user_id))

    old_role = user.role.value
    user.role = body.role
    await db.commit()
    await db.refresh(user)

    logger.info(
        f"Admin {current_user.id} changed user {user_id} role: {old_role} → {user.role.value}"
    )

    return {
        "message": f"Role updated successfully",
        "data": {
            "id": str(user.id),
            "email": user.email,
            "old_role": old_role,
            "new_role": user.role.value,
        },
    }


@router.post("/users/{user_id}/kyc/approve", response_model=Dict[str, Any])
async def approve_user_kyc(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually approve a user's KYC from user management — admin only.

    Fallback for when a user (e.g. an advisor) can't get verified through Persona
    self-service. Works whether or not they ever started Persona: the account and a
    KYC record are created if missing, then marked APPROVED. Admins don't need KYC,
    so approving an admin is rejected.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", str(user_id))
    if user.role == Role.ADMIN:
        raise BadRequestException("Admins do not require KYC verification.")

    # Ensure the user has an account (auto-create, mirroring KYC start).
    account_result = await db.execute(select(Account).where(Account.user_id == user.id))
    account = account_result.scalar_one_or_none()
    if not account:
        account_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email.split("@")[0]
        account = Account(
            user_id=user.id,
            account_type=AccountType.INDIVIDUAL,
            account_name=account_name,
            is_joint=False,
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)

    # Find or create the KYC record, then approve it.
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    if kyc and kyc.status == KYCStatus.APPROVED:
        raise BadRequestException("KYC is already approved")

    if not kyc:
        kyc = KYCVerification(
            account_id=account.id,
            status=KYCStatus.APPROVED,
            verification_level="manual_admin",
            verified_at=datetime.utcnow(),
        )
        db.add(kyc)
    else:
        kyc.status = KYCStatus.APPROVED
        kyc.verified_at = datetime.utcnow()
        kyc.rejection_reason = None
    await db.commit()
    await db.refresh(kyc)

    # Notify the user.
    try:
        from app.services.notification_service import NotificationService, NotificationType
        await NotificationService.create_notification(
            db=db,
            account_id=account.id,
            notification_type=NotificationType.KYC_APPROVED,
            title="KYC Verification Approved",
            message="Your identity verification has been approved by an administrator. You now have full access.",
        )
    except Exception as e:
        logger.warning(f"Failed to send KYC approval notification: {e}")

    kyc.reviewed_by = current_user.id
    kyc.reviewed_at = datetime.utcnow()
    await db.commit()

    logger.info(f"Admin {current_user.id} manually approved KYC for user {user_id}")
    return {
        "message": "KYC approved",
        "data": {
            "user_id": str(user.id),
            "account_id": str(account.id),
            "kyc_id": str(kyc.id),
            "status": kyc.status.value,
        },
    }


class KYCRejectRequest(BaseModel):
    reason: str


async def _load_user_account_kyc(db: AsyncSession, user_id: UUID):
    """Resolve (user, account, kyc) for the admin KYC endpoints, or raise 404."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise NotFoundException("User", str(user_id))
    account = (await db.execute(select(Account).where(Account.user_id == user.id))).scalar_one_or_none()
    kyc = None
    if account:
        kyc = (await db.execute(
            select(KYCVerification).where(KYCVerification.account_id == account.id)
        )).scalar_one_or_none()
    return user, account, kyc


@router.get("/users/{user_id}/kyc", response_model=Dict[str, Any])
async def get_user_kyc_detail(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Full KYC review payload for a user — admin only.

    Returns the (Persona-driven) status, extracted identity fields, per-check
    results, capture state, and each stored document with a short-lived signed URL
    the admin can open to view the image (the bucket itself stays private).
    """
    from app.integrations.supabase_client import SupabaseClient

    user, account, kyc = await _load_user_account_kyc(db, user_id)
    if not kyc:
        return {
            "data": {
                "user_id": str(user.id),
                "account_id": str(account.id) if account else None,
                "status": KYCStatus.NOT_STARTED.value,
                "capture_status": KYCCaptureStatus.NOT_CAPTURED.value,
                "extracted_fields": None,
                "checks": None,
                "documents": [],
            }
        }

    docs = (await db.execute(
        select(KYCDocument).where(KYCDocument.kyc_id == kyc.id).order_by(KYCDocument.document_type)
    )).scalars().all()

    documents = []
    for d in docs:
        signed = SupabaseClient.create_signed_url(d.bucket, d.file_path, settings.KYC_SIGNED_URL_EXPIRY)
        documents.append({
            "id": str(d.id),
            "document_type": d.document_type,
            "mime_type": d.mime_type,
            "file_size": d.file_size,
            "view_url": signed,  # short-lived; refetch this endpoint to renew
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })

    return {
        "data": {
            "user_id": str(user.id),
            "account_id": str(account.id),
            "kyc_id": str(kyc.id),
            "persona_inquiry_id": kyc.persona_inquiry_id,
            "status": kyc.status.value,
            "capture_status": kyc.capture_status.value if kyc.capture_status else KYCCaptureStatus.NOT_CAPTURED.value,
            "capture_error": kyc.capture_error,
            "captured_at": kyc.captured_at.isoformat() if kyc.captured_at else None,
            "verified_at": kyc.verified_at.isoformat() if kyc.verified_at else None,
            "rejection_reason": kyc.rejection_reason,
            "reviewed_by": str(kyc.reviewed_by) if kyc.reviewed_by else None,
            "reviewed_at": kyc.reviewed_at.isoformat() if kyc.reviewed_at else None,
            "extracted_fields": kyc.extracted_fields,
            "checks": kyc.checks,
            "documents": documents,
            "signed_url_expires_in": settings.KYC_SIGNED_URL_EXPIRY,
        }
    }


@router.post("/users/{user_id}/kyc/reject", response_model=Dict[str, Any])
async def reject_user_kyc(
    user_id: UUID,
    body: KYCRejectRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually reject/override a user's KYC after reviewing the captured docs — admin only."""
    reason = (body.reason or "").strip()
    if not reason:
        raise BadRequestException("A rejection reason is required")

    user, account, kyc = await _load_user_account_kyc(db, user_id)
    if user.role == Role.ADMIN:
        raise BadRequestException("Admins do not require KYC verification.")
    if not account or not kyc:
        raise NotFoundException("KYC record", str(user_id))

    kyc.status = KYCStatus.REJECTED
    kyc.rejection_reason = reason
    kyc.reviewed_by = current_user.id
    kyc.reviewed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(kyc)

    try:
        from app.services.notification_service import NotificationService, NotificationType
        await NotificationService.create_notification(
            db=db,
            account_id=account.id,
            notification_type=NotificationType.GENERAL,
            title="KYC Verification Rejected",
            message=f"Your identity verification was not approved. Reason: {reason}",
        )
    except Exception as e:
        logger.warning(f"Failed to send KYC rejection notification: {e}")

    logger.info(f"Admin {current_user.id} rejected KYC for user {user_id}")
    return {
        "message": "KYC rejected",
        "data": {"user_id": str(user.id), "kyc_id": str(kyc.id), "status": kyc.status.value},
    }


@router.post("/users/{user_id}/kyc/recapture", response_model=Dict[str, Any])
async def recapture_user_kyc(
    user_id: UUID,
    background: BackgroundTasks,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Re-run the Persona document capture for a user (e.g. after a failed capture) — admin only."""
    user, account, kyc = await _load_user_account_kyc(db, user_id)
    if not account or not kyc:
        raise NotFoundException("KYC record", str(user_id))
    if not kyc.persona_inquiry_id:
        raise BadRequestException("This user has no Persona inquiry to capture from.")

    from app.services.persona_capture import PersonaCaptureService
    background.add_task(PersonaCaptureService.capture, account.id, kyc.persona_inquiry_id)

    logger.info(f"Admin {current_user.id} triggered KYC re-capture for user {user_id}")
    return {
        "message": "Re-capture started",
        "data": {"user_id": str(user.id), "kyc_id": str(kyc.id), "capture_status": KYCCaptureStatus.PENDING.value},
    }


@router.patch("/users/{user_id}/deactivate", response_model=Dict[str, Any])
async def deactivate_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user account — admin only"""
    if user_id == current_user.id:
        raise BadRequestException("You cannot deactivate your own account")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", str(user_id))

    user.is_active = False
    user.deactivated_at = datetime.utcnow()
    await db.commit()

    logger.info(f"Admin {current_user.id} deactivated user {user_id}")
    return {"message": "User deactivated", "data": {"id": str(user_id), "is_active": False}}


@router.patch("/users/{user_id}/activate", response_model=Dict[str, Any])
async def activate_user(
    user_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a user account — admin only"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", str(user_id))

    user.is_active = True
    user.deactivated_at = None
    await db.commit()

    logger.info(f"Admin {current_user.id} activated user {user_id}")
    return {"message": "User activated", "data": {"id": str(user_id), "is_active": True}}


# ==================== SUBSCRIPTIONS MANAGEMENT ====================

class PlanUpdateRequest(BaseModel):
    """Admin plan-change request.

    Mirrors the user-facing ``PUT /subscriptions/upgrade`` contract:
      - ``plan_id``: the product tier — "starter" | "pro" | "premium" | "concierge"
      - ``billing_cycle``: "monthly" | "annual" (optional; inferred if omitted)

    For backward compatibility with the existing admin UI, a single ``plan``
    value is still accepted and resolved the same way. It may be a product tier
    (starter/pro/premium/concierge) OR a legacy internal value
    (free/monthly/annual). When ``plan`` is "monthly"/"annual" it is also treated
    as the billing cycle if ``billing_cycle`` is not given.
    """
    plan_id: Optional[str] = None
    billing_cycle: Optional[str] = None
    plan: Optional[str] = None  # legacy single-value field
    reason: Optional[str] = None


# Legacy single-value "plan" inputs (billing-cycle-style) → a representative
# product plan_id, so old payloads keep resolving to a valid tier.
_LEGACY_PLAN_TO_PLAN_ID = {
    "free": "starter",
    "monthly": "pro",
    "annual": "premium",
}


def resolve_admin_plan_id(raw: Optional[str]) -> Optional[str]:
    """Resolve any accepted plan identifier to a canonical product ``plan_id``
    ("starter" | "pro" | "premium" | "concierge"), or None if unrecognized.

    Accepts product IDs (optionally "plan_"-prefixed) and legacy internal enum
    values (free/monthly/annual). All resolution reuses the canonical maps in
    ``subscriptions.py`` so the admin and user-facing endpoints never drift.
    """
    # Local import avoids any import-order coupling between the two routers.
    from app.api.v1.subscriptions import PLANS_CONFIG, normalize_plan_id

    if not raw:
        return None
    key = raw.strip().lower()
    normalized = normalize_plan_id(key)
    if normalized in PLANS_CONFIG:
        return normalized
    return _LEGACY_PLAN_TO_PLAN_ID.get(key)


@router.get("/subscriptions", response_model=Dict[str, Any])
async def list_all_subscriptions(
    plan: Optional[str] = Query(None, description="Filter by plan: free | monthly | annual"),
    sub_status: Optional[str] = Query(None, alias="status", description="Filter by status: active | cancelled | expired | past_due"),
    search: Optional[str] = Query(None, description="Search by user email or name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all subscriptions across all accounts — admin only"""
    from sqlalchemy import or_
    from app.api.v1.subscriptions import PLANS_CONFIG, get_plan_tier, get_billing_cycle

    # Join subscriptions → accounts → users for search. Only investors hold plans,
    # so admin/advisor accounts are excluded from billing views.
    query = (
        select(Subscription, Account, User)
        .join(Account, Subscription.account_id == Account.id)
        .join(User, Account.user_id == User.id)
        .where(User.role == Role.INVESTOR)
    )
    count_query = (
        select(func.count(Subscription.id))
        .join(Account, Subscription.account_id == Account.id)
        .join(User, Account.user_id == User.id)
        .where(User.role == Role.INVESTOR)
    )

    if plan:
        # Filter by the product tier (starter/pro/premium). Accepts tier IDs and
        # legacy free/monthly/annual values; all resolve to a canonical tier.
        tier = resolve_admin_plan_id(plan) or plan
        query = query.where(Subscription.plan_tier == tier)
        count_query = count_query.where(Subscription.plan_tier == tier)

    if sub_status:
        query = query.where(Subscription.status == sub_status)
        count_query = count_query.where(Subscription.status == sub_status)

    if search:
        search_filter = or_(
            User.email.ilike(f"%{search}%"),
            User.first_name.ilike(f"%{search}%"),
            User.last_name.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await db.execute(
        query.order_by(Subscription.created_at.desc()).offset(offset).limit(page_size)
    )
    rows = result.all()

    data = []
    for sub, acc, usr in rows:
        plan_id = get_plan_tier(sub)
        plan_config = PLANS_CONFIG.get(plan_id, PLANS_CONFIG["starter"])
        data.append({
            "id": str(sub.id),
            "account_id": str(sub.account_id),
            "user_id": str(usr.id),
            "user_email": usr.email,
            "user_name": f"{usr.first_name or ''} {usr.last_name or ''}".strip() or None,
            # Real product tier the customer bought (fixes "$49 shows Free").
            "plan_id": plan_id,
            "plan_name": plan_config["name"],
            "billing_cycle": get_billing_cycle(sub),
            # Legacy internal enum kept for backward compatibility with old clients.
            "plan": sub.plan.value,
            "status": sub.status.value,
            "amount": float(sub.amount),
            "currency": sub.currency,
            "cancel_at_period_end": bool(getattr(sub, "cancel_at_period_end", False)),
            "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "cancelled_at": sub.cancelled_at.isoformat() if sub.cancelled_at else None,
            "stripe_subscription_id": sub.stripe_subscription_id,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        })

    return {
        "data": data,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        },
    }


@router.patch("/subscriptions/{subscription_id}/cancel", response_model=Dict[str, Any])
async def admin_cancel_subscription(
    subscription_id: UUID,
    reason: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Force-cancel any subscription — admin only"""
    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise NotFoundException("Subscription", str(subscription_id))

    if sub.status == SubscriptionStatus.CANCELLED:
        raise BadRequestException("Subscription is already cancelled")

    sub.status = SubscriptionStatus.CANCELLED
    sub.cancelled_at = datetime.utcnow()
    await db.commit()

    logger.info(f"Admin {current_user.id} cancelled subscription {subscription_id}. Reason: {reason}")
    return {
        "message": "Subscription cancelled",
        "data": {
            "id": str(sub.id),
            "account_id": str(sub.account_id),
            "plan": sub.plan.value,
            "status": sub.status.value,
            "cancelled_at": sub.cancelled_at.isoformat(),
        },
    }


@router.patch("/subscriptions/{subscription_id}/plan", response_model=Dict[str, Any])
async def admin_change_subscription_plan(
    subscription_id: UUID,
    body: PlanUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Change a user's subscription plan — admin only.

    Request body (aligned with the user-facing ``PUT /subscriptions/upgrade``):
        { "plan_id": "pro", "billing_cycle": "monthly", "reason": "..." }

    ``plan_id`` ∈ starter | pro | premium | concierge.
    ``billing_cycle`` ∈ monthly | annual (optional — inferred from the current
    period, or defaults to monthly).

    Backward compatible: a single ``plan`` value (a product tier OR a legacy
    free/monthly/annual value) is still accepted. Unknown values return 400,
    never 500.
    """
    from app.api.v1.subscriptions import (
        PLAN_ID_TO_ENUM, PLAN_ENUM_TO_ID, PLAN_PRICES,
    )

    # 1) Resolve the target product plan_id from either field.
    raw_plan = body.plan_id or body.plan
    plan_id = resolve_admin_plan_id(raw_plan)
    if plan_id is None:
        raise BadRequestException(
            "Invalid plan. Provide plan_id one of: starter, pro, premium, concierge "
            "(legacy plan values free/monthly/annual are also accepted)."
        )

    # 2) Resolve the billing cycle: explicit > legacy cycle-style 'plan' > existing > monthly.
    billing_cycle = (body.billing_cycle or "").strip().lower() or None
    if billing_cycle is None and body.plan and body.plan.strip().lower() in ("monthly", "annual"):
        billing_cycle = body.plan.strip().lower()

    result = await db.execute(
        select(Subscription).where(Subscription.id == subscription_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise NotFoundException("Subscription", str(subscription_id))

    if billing_cycle is None:
        if sub.current_period_start and sub.current_period_end:
            days = (sub.current_period_end - sub.current_period_start).days
            billing_cycle = "annual" if days > 60 else "monthly"
        else:
            billing_cycle = "monthly"
    if billing_cycle not in ("monthly", "annual"):
        raise BadRequestException("billing_cycle must be 'monthly' or 'annual'")

    old_plan_id = PLAN_ENUM_TO_ID.get(sub.plan, sub.plan.value if sub.plan else None)
    internal_plan = PLAN_ID_TO_ENUM.get(plan_id, SubscriptionPlan.FREE)

    # 3) Apply plan + price + a fresh billing period coherently.
    sub.plan = internal_plan
    sub.plan_tier = plan_id
    sub.billing_cycle = billing_cycle
    price = PLAN_PRICES.get(plan_id, {}).get(billing_cycle)
    if price is not None:  # concierge has custom (None) pricing — leave amount as-is
        sub.amount = price
    now = datetime.now(timezone.utc)
    sub.current_period_start = now
    sub.current_period_end = now + (timedelta(days=365) if billing_cycle == "annual" else timedelta(days=30))
    # An explicit plan change clears any pending end-of-period cancellation.
    sub.cancel_at_period_end = False

    # Reactivate if it was expired/cancelled
    if sub.status in (SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED):
        sub.status = SubscriptionStatus.ACTIVE
        sub.cancelled_at = None

    await db.commit()

    logger.info(
        f"Admin {current_user.id} changed subscription {subscription_id} plan: "
        f"{old_plan_id} → {plan_id} ({billing_cycle}). Reason: {body.reason}"
    )
    return {
        "message": "Subscription plan updated",
        "data": {
            "id": str(sub.id),
            "account_id": str(sub.account_id),
            "old_plan": old_plan_id,
            "new_plan": plan_id,
            "plan_id": plan_id,
            "billing_cycle": billing_cycle,
            "internal_plan": sub.plan.value,
            "amount": float(sub.amount) if sub.amount is not None else None,
            "currency": sub.currency,
            "status": sub.status.value,
            "current_period_end": sub.current_period_end.isoformat(),
        },
    }


# ==================== ADMIN SUPPORT DASHBOARD (read-only) ====================
# Dedicated admin-scoped, read-only endpoints powering /dashboard/support-dashboard.
# These are SEPARATE from /support/* and /chat/* — those existing APIs are unchanged.

from sqlalchemy.orm import aliased


def _full_name(u) -> Optional[str]:
    if u is None:
        return None
    return f"{u.first_name or ''} {u.last_name or ''}".strip() or u.email


def _asset_request_row(req_type: str, req, asset, usr, assignee=None) -> Dict[str, Any]:
    created = getattr(req, "created_at", None) or getattr(req, "requested_at", None)
    status_val = req.status.value if hasattr(req.status, "value") else str(req.status)
    return {
        "id": str(req.id),
        "type": req_type,  # "appraisal" | "sale"
        "status": status_val,
        "asset": {"id": str(asset.id), "name": asset.name},
        "requested_by": {"id": str(usr.id), "name": _full_name(usr), "email": usr.email},
        "assigned_advisor": (
            {"id": str(assignee.id), "name": _full_name(assignee)} if assignee else None
        ),
        "created_at": created.isoformat() if created else None,
    }


@router.get("/support/tickets", response_model=Dict[str, Any])
async def admin_list_tickets(
    ticket_status: Optional[TicketStatus] = Query(None, alias="status", description="open | in_progress | resolved | closed"),
    search: Optional[str] = Query(None, description="Search subject/description or requester name/email"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """All support tickets across all users — admin only, rich shape for the dashboard."""
    from sqlalchemy import or_

    Requester = aliased(User)
    Assignee = aliased(User)
    q = (
        select(SupportTicket, Requester, Assignee)
        .join(Account, SupportTicket.account_id == Account.id)
        .join(Requester, Account.user_id == Requester.id)
        .outerjoin(Assignee, SupportTicket.assigned_to == Assignee.id)
    )
    if ticket_status:
        q = q.where(SupportTicket.status == ticket_status)
    if search:
        like = f"%{search}%"
        q = q.where(or_(
            SupportTicket.subject.ilike(like),
            SupportTicket.description.ilike(like),
            Requester.email.ilike(like),
            Requester.first_name.ilike(like),
            Requester.last_name.ilike(like),
        ))
    q = q.order_by(SupportTicket.created_at.desc()).limit(limit)
    rows = (await db.execute(q)).all()

    data = []
    for ticket, requester, assignee in rows:
        data.append({
            "id": str(ticket.id),
            "subject": ticket.subject,
            "description": ticket.description,
            "status": ticket.status.value,
            "priority": ticket.priority.value,
            "category": ticket.category,
            "user_name": _full_name(requester),
            "user_email": requester.email if requester else None,
            "assigned_advisor": (
                {"id": str(assignee.id), "name": _full_name(assignee)} if assignee else None
            ),
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        })
    return {"data": data, "total": len(data), "limit": limit}


@router.get("/asset-requests", response_model=Dict[str, Any])
async def admin_list_asset_requests(
    request_type: Optional[str] = Query(None, alias="type", description="appraisal | sale"),
    req_status: Optional[str] = Query(None, alias="status", description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by asset name or requester name/email"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Global, admin-scoped feed of asset requests (appraisals + sale requests)."""
    from sqlalchemy import or_
    from app.models.asset import AssetAppraisal, AssetSaleRequest, AppraisalStatus, SaleRequestStatus

    want = (request_type or "").strip().lower() or None
    like = f"%{search}%" if search else None
    Requester = aliased(User)
    Assignee = aliased(User)

    def search_clause():
        return or_(
            Asset.name.ilike(like),
            Requester.email.ilike(like),
            Requester.first_name.ilike(like),
            Requester.last_name.ilike(like),
        )

    rows: List[Dict[str, Any]] = []

    # Appraisals
    if want in (None, "appraisal"):
        status_enum = None
        skip = False
        if req_status:
            try:
                status_enum = AppraisalStatus(req_status.strip().lower())
            except ValueError:
                skip = True  # status not valid for appraisals -> no appraisal rows
        if not skip:
            q = (
                select(AssetAppraisal, Asset, Requester, Assignee)
                .join(Asset, AssetAppraisal.asset_id == Asset.id)
                .join(Account, Asset.account_id == Account.id)
                .join(Requester, Account.user_id == Requester.id)
                .outerjoin(Assignee, AssetAppraisal.assigned_to == Assignee.id)
            )
            if status_enum is not None:
                q = q.where(AssetAppraisal.status == status_enum)
            if like:
                q = q.where(search_clause())
            for ap, asset, usr, assignee in (await db.execute(q)).all():
                rows.append(_asset_request_row("appraisal", ap, asset, usr, assignee))

    # Sale requests
    if want in (None, "sale"):
        status_enum = None
        skip = False
        if req_status:
            try:
                status_enum = SaleRequestStatus(req_status.strip().lower())
            except ValueError:
                skip = True
        if not skip:
            q = (
                select(AssetSaleRequest, Asset, Requester, Assignee)
                .join(Asset, AssetSaleRequest.asset_id == Asset.id)
                .join(Account, Asset.account_id == Account.id)
                .join(Requester, Account.user_id == Requester.id)
                .outerjoin(Assignee, AssetSaleRequest.assigned_to == Assignee.id)
            )
            if status_enum is not None:
                q = q.where(AssetSaleRequest.status == status_enum)
            if like:
                q = q.where(search_clause())
            for sr, asset, usr, assignee in (await db.execute(q)).all():
                rows.append(_asset_request_row("sale", sr, asset, usr, assignee))

    rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
    total = len(rows)
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]
    return {
        "data": page_rows,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        },
    }


class AssignAssetRequestBody(BaseModel):
    advisor_id: UUID


@router.post("/asset-requests/{request_type}/{request_id}/assign", response_model=Dict[str, Any])
async def admin_assign_asset_request(
    request_type: str,
    request_id: UUID,
    body: AssignAssetRequestBody,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Assign an advisor (or admin) to handle an asset request — admin only."""
    from app.models.asset import AssetAppraisal, AssetSaleRequest

    rt = (request_type or "").strip().lower()
    Model = {"appraisal": AssetAppraisal, "sale": AssetSaleRequest}.get(rt)
    if Model is None:
        raise BadRequestException("request_type must be 'appraisal' or 'sale'.")

    req = (await db.execute(select(Model).where(Model.id == request_id))).scalar_one_or_none()
    if not req:
        raise NotFoundException("Asset request", str(request_id))

    advisor = (await db.execute(select(User).where(User.id == body.advisor_id))).scalar_one_or_none()
    if not advisor:
        raise NotFoundException("User", str(body.advisor_id))
    if advisor.role not in (Role.ADVISOR, Role.ADMIN):
        raise BadRequestException("Assignee must be an advisor or admin.")

    req.assigned_to = advisor.id
    await db.commit()

    logger.info(f"Admin {current_user.id} assigned {rt} request {request_id} to {advisor.id}")
    return {
        "message": "Asset request assigned",
        "data": {
            "id": str(req.id),
            "type": rt,
            "assigned_advisor": {"id": str(advisor.id), "name": _full_name(advisor)},
        },
    }


async def _build_conversation_row(db: AsyncSession, conv, viewer_id) -> Dict[str, Any]:
    from sqlalchemy import and_
    from app.models.chat import ConversationParticipant, Message, MessageRead

    parts = (await db.execute(
        select(ConversationParticipant).where(ConversationParticipant.conversation_id == conv.id)
    )).scalars().all()
    participants = []
    for p in parts:
        u = (await db.execute(select(User).where(User.id == p.user_id))).scalar_one_or_none()
        if u:
            participants.append({
                "user_id": str(u.id),
                "name": _full_name(u),
                "role": u.role.value,            # system role: investor | advisor | admin
                "participant_role": p.role.value,  # conversation role: participant | admin | moderator
            })

    last = (await db.execute(
        select(Message).where(Message.conversation_id == conv.id)
        .order_by(Message.timestamp.desc()).limit(1)
    )).scalar_one_or_none()
    last_message = None
    if last:
        sender = (await db.execute(select(User).where(User.id == last.sender_id))).scalar_one_or_none()
        last_message = {
            "id": str(last.id),
            "content": (last.content or "")[:200],
            "sender_id": str(last.sender_id),
            "sender_name": _full_name(sender),
            "timestamp": last.timestamp.isoformat() if last.timestamp else None,
        }

    unread = (await db.execute(
        select(func.count(Message.id)).select_from(Message).outerjoin(
            MessageRead,
            and_(MessageRead.message_id == Message.id, MessageRead.user_id == viewer_id),
        ).where(and_(
            Message.conversation_id == conv.id,
            Message.sender_id != viewer_id,
            MessageRead.id.is_(None),
        ))
    )).scalar() or 0

    ts = conv.updated_at or conv.created_at
    return {
        "id": str(conv.id),
        "subject": conv.subject,
        "participants": participants,
        "last_message": last_message,
        "unread_count": unread,
        "updated_at": ts.isoformat() if ts else None,
    }


@router.get("/support/conversations", response_model=Dict[str, Any])
async def admin_list_conversations(
    conv_status: Optional[str] = Query("all", alias="status", description="active | archived | all"),
    search: Optional[str] = Query(None, description="Search by participant name/email or subject"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """All conversations (including advisor<->investor) — admin only, read-only."""
    from app.models.chat import Conversation, ConversationStatus

    q = select(Conversation)
    if conv_status == "active":
        q = q.where(Conversation.status == ConversationStatus.ACTIVE)
    elif conv_status == "archived":
        q = q.where(Conversation.status == ConversationStatus.ARCHIVED)
    q = q.order_by(func.coalesce(Conversation.updated_at, Conversation.created_at).desc())

    if search:
        # Search needs participant/subject matching -> build rows then filter in-memory.
        # Bounded to the most recent 500 conversations to cap cost.
        convs = (await db.execute(q.limit(500))).scalars().all()
        all_rows = [await _build_conversation_row(db, c, current_user.id) for c in convs]
        s = search.lower()
        filtered = [
            r for r in all_rows
            if (r["subject"] and s in r["subject"].lower())
            or any(s in (p["name"] or "").lower() for p in r["participants"])
        ]
        total = len(filtered)
        page_rows = filtered[offset:offset + limit]
    else:
        total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
        convs = (await db.execute(q.offset(offset).limit(limit))).scalars().all()
        page_rows = [await _build_conversation_row(db, c, current_user.id) for c in convs]

    return {"data": page_rows, "total": total, "limit": limit, "offset": offset}


@router.get("/support/conversations/{conversation_id}/messages", response_model=Dict[str, Any])
async def admin_get_conversation_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Read messages for ANY conversation — admin only (no participant requirement)."""
    from app.models.chat import Conversation, Message

    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one_or_none()
    if not conv:
        raise NotFoundException("Conversation", str(conversation_id))

    msgs = (await db.execute(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.timestamp.desc()).limit(limit)
    )).scalars().all()

    data = []
    for m in reversed(msgs):  # oldest first
        sender = (await db.execute(select(User).where(User.id == m.sender_id))).scalar_one_or_none()
        data.append({
            "id": str(m.id),
            "conversation_id": str(m.conversation_id),
            "sender_id": str(m.sender_id),
            "sender_name": _full_name(sender),
            "sender_role": sender.role.value if sender else None,
            "content": m.content,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
        })
    return {"data": data, "count": len(data)}


@router.get("/support/analytics", response_model=Dict[str, Any])
async def admin_support_analytics(
    range: str = Query("30d", description="7d | 30d | 90d"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Support analytics for the Reports tab, computed from real data.

    Note: `satisfaction_rate` has no backend source yet (no CSAT/feedback model),
    so it is returned as null with a note until a feedback mechanism exists.
    """
    from sqlalchemy import and_
    from app.models.chat import Message

    days = {"7d": 7, "30d": 30, "90d": 90}.get((range or "30d").lower(), 30)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    def pct(cur, prev):
        if not prev or cur is None:
            return None
        return round((cur - prev) / prev * 100, 1)

    # total chats handled = distinct conversations with messages in the window
    cur_chats = (await db.execute(
        select(func.count(func.distinct(Message.conversation_id))).where(Message.timestamp >= start)
    )).scalar() or 0
    prev_chats = (await db.execute(
        select(func.count(func.distinct(Message.conversation_id)))
        .where(and_(Message.timestamp >= prev_start, Message.timestamp < start))
    )).scalar() or 0

    # avg first-response time (seconds) for tickets first-responded in the window
    avg_cur = (await db.execute(
        select(func.avg(func.extract("epoch", SupportTicket.first_response_at - SupportTicket.created_at)))
        .where(and_(SupportTicket.first_response_at.isnot(None), SupportTicket.created_at >= start))
    )).scalar()
    avg_prev = (await db.execute(
        select(func.avg(func.extract("epoch", SupportTicket.first_response_at - SupportTicket.created_at)))
        .where(and_(SupportTicket.first_response_at.isnot(None),
                    SupportTicket.created_at >= prev_start, SupportTicket.created_at < start))
    )).scalar()
    avg_cur_s = int(avg_cur) if avg_cur is not None else None
    avg_prev_s = int(avg_prev) if avg_prev is not None else None

    # unresolved issues = current open + in_progress (snapshot)
    unresolved = (await db.execute(
        select(func.count(SupportTicket.id))
        .where(SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS]))
    )).scalar() or 0

    # chats per agent = messages sent by advisor/admin users in the window
    agent_rows = (await db.execute(
        select(User.id, User.first_name, User.last_name, User.email, func.count(Message.id))
        .join(User, Message.sender_id == User.id)
        .where(and_(Message.timestamp >= start, User.role.in_([Role.ADVISOR, Role.ADMIN])))
        .group_by(User.id, User.first_name, User.last_name, User.email)
        .order_by(func.count(Message.id).desc())
    )).all()
    chats_per_agent = [
        {"agent_id": str(r[0]), "agent_name": (f"{r[1] or ''} {r[2] or ''}".strip() or r[3]), "count": r[4]}
        for r in agent_rows
    ]

    # common topics = ticket categories in the window
    topic_rows = (await db.execute(
        select(SupportTicket.category, func.count(SupportTicket.id))
        .where(and_(SupportTicket.created_at >= start, SupportTicket.category.isnot(None)))
        .group_by(SupportTicket.category)
        .order_by(func.count(SupportTicket.id).desc())
        .limit(10)
    )).all()
    common_topics = [{"topic": t[0], "count": t[1]} for t in topic_rows]

    # satisfaction rate = avg CSAT rating (1-5) -> percentage, over tickets rated
    # for work created in the window.
    def rating_pct(avg):
        return round(float(avg) / 5 * 100, 1) if avg is not None else None

    cur_rating = (await db.execute(
        select(func.avg(SupportTicket.satisfaction_rating))
        .where(and_(SupportTicket.satisfaction_rating.isnot(None), SupportTicket.created_at >= start))
    )).scalar()
    prev_rating = (await db.execute(
        select(func.avg(SupportTicket.satisfaction_rating))
        .where(and_(SupportTicket.satisfaction_rating.isnot(None),
                    SupportTicket.created_at >= prev_start, SupportTicket.created_at < start))
    )).scalar()
    sat_value = rating_pct(cur_rating)
    prev_sat_value = rating_pct(prev_rating)

    def label(sec):
        if sec is None:
            return None
        sec = int(sec)
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    return {
        "range": f"{days}d",
        "summary": {
            "total_chats_handled": {"value": cur_chats, "change_pct": pct(cur_chats, prev_chats)},
            "avg_response_time": {
                "value_seconds": avg_cur_s,
                "value_label": label(avg_cur_s),
                "change_pct": pct(avg_cur_s, avg_prev_s),
            },
            "unresolved_issues": {"value": unresolved, "change_pct": None},
            "satisfaction_rate": {
                "value": sat_value,  # percentage (0-100), or null if no ratings yet
                "change_pct": pct(sat_value, prev_sat_value),
                "note": None if sat_value is not None else "No CSAT ratings submitted in this period yet.",
            },
        },
        "chats_per_agent": chats_per_agent,
        "common_topics": common_topics,
    }


# ==================== ADVISOR <-> CLIENT ASSIGNMENT ====================


async def _get_or_create_advisor_chat(db: AsyncSession, advisor, client):
    """Auto-create the advisor<->investor conversation with both as participants."""
    from app.models.chat import Conversation, ConversationParticipant, ConversationStatus, ParticipantRole
    conv = Conversation(subject=f"Advisor — {_full_name(client)}", status=ConversationStatus.ACTIVE)
    db.add(conv)
    await db.flush()  # populate conv.id
    db.add(ConversationParticipant(conversation_id=conv.id, user_id=advisor.id, role=ParticipantRole.PARTICIPANT))
    db.add(ConversationParticipant(conversation_id=conv.id, user_id=client.id, role=ParticipantRole.PARTICIPANT))
    return conv


class AssignClientBody(BaseModel):
    investor_id: UUID


@router.post("/advisors/{advisor_id}/clients", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def admin_assign_client(
    advisor_id: UUID,
    body: AssignClientBody,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Assign an investor to an advisor — admin only.

    Auto-creates the advisor<->investor chat, notifies both parties, and returns
    the new conversation_id. An investor may have only one advisor at a time.
    """
    from app.models.advisor_client import AdvisorClient
    from app.models.notification import NotificationType

    advisor = (await db.execute(select(User).where(User.id == advisor_id))).scalar_one_or_none()
    if not advisor:
        raise NotFoundException("User", str(advisor_id))
    if advisor.role != Role.ADVISOR:
        raise BadRequestException("Target user is not an advisor.")

    client = (await db.execute(select(User).where(User.id == body.investor_id))).scalar_one_or_none()
    if not client:
        raise NotFoundException("User", str(body.investor_id))
    if client.role != Role.INVESTOR:
        raise BadRequestException("Only an investor can be assigned to an advisor.")

    existing = (await db.execute(
        select(AdvisorClient).where(AdvisorClient.client_id == client.id)
    )).scalar_one_or_none()
    if existing:
        if existing.advisor_id == advisor.id:
            raise ConflictException("This investor is already assigned to this advisor.")
        raise ConflictException("This investor already has an advisor. Unassign first.")

    conv = await _get_or_create_advisor_chat(db, advisor, client)
    assignment = AdvisorClient(
        advisor_id=advisor.id, client_id=client.id,
        conversation_id=conv.id, assigned_by=current_user.id,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)

    # Notify both parties (bell + realtime WS) via the shared service.
    from app.services.notification_service import NotificationService
    meta = json.dumps({
        "event": "client_assigned",
        "conversation_id": str(conv.id),
        "advisor_id": str(advisor.id),
        "investor_id": str(client.id),
    })
    await NotificationService.notify_user(
        db, advisor.id, NotificationType.GENERAL, "New client assigned",
        f"You've been assigned to help {_full_name(client)}.", meta)
    await NotificationService.notify_user(
        db, client.id, NotificationType.GENERAL, "Your advisor is ready",
        f"{_full_name(advisor)} has been assigned as your advisor.", meta)

    logger.info(f"Admin {current_user.id} assigned investor {client.id} to advisor {advisor.id}")
    return {
        "message": "Investor assigned to advisor",
        "data": {
            "assignment_id": str(assignment.id),
            "advisor_id": str(advisor.id),
            "investor_id": str(client.id),
            "conversation_id": str(conv.id),
        },
    }


@router.get("/advisors/{advisor_id}/clients", response_model=Dict[str, Any])
async def admin_list_advisor_clients(
    advisor_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List the investors assigned to an advisor — admin only."""
    from app.models.advisor_client import AdvisorClient

    Client = aliased(User)
    rows = (await db.execute(
        select(AdvisorClient, Client)
        .join(Client, AdvisorClient.client_id == Client.id)
        .where(AdvisorClient.advisor_id == advisor_id)
        .order_by(AdvisorClient.created_at.desc())
    )).all()
    data = [{
        "client_id": str(c.id),
        "name": _full_name(c),
        "email": c.email,
        "conversation_id": str(ac.conversation_id) if ac.conversation_id else None,
        "assigned_at": ac.created_at.isoformat() if ac.created_at else None,
    } for ac, c in rows]
    return {"data": data, "total": len(data)}


@router.delete("/advisors/{advisor_id}/clients/{investor_id}", response_model=Dict[str, Any])
async def admin_unassign_client(
    advisor_id: UUID,
    investor_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Unassign an investor from an advisor — admin only. The chat history is kept."""
    from app.models.advisor_client import AdvisorClient

    row = (await db.execute(
        select(AdvisorClient).where(
            AdvisorClient.advisor_id == advisor_id,
            AdvisorClient.client_id == investor_id,
        )
    )).scalar_one_or_none()
    if not row:
        raise NotFoundException("Advisor assignment", str(investor_id))

    await db.delete(row)
    await db.commit()
    logger.info(f"Admin {current_user.id} unassigned investor {investor_id} from advisor {advisor_id}")
    return {
        "message": "Client unassigned",
        "data": {"advisor_id": str(advisor_id), "investor_id": str(investor_id)},
    }


# ==================== VERIFICATIONS MANAGEMENT ====================

class RejectRequest(BaseModel):
    reason: str


@router.get("/verifications", response_model=Dict[str, Any])
async def list_all_verifications(
    verification_type: Optional[str] = Query(None, description="Filter: kyc | kyb | all (default all)"),
    ver_status: Optional[str] = Query(None, alias="status", description="Filter by status: not_started | in_progress | pending_review | approved | rejected | expired"),
    search: Optional[str] = Query(None, description="Search by user email or name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Combined KYC + KYB verification queue — admin only"""
    from sqlalchemy import or_, union_all, literal
    from app.models.kyb import KYBVerification, KYBStatus

    results = []

    # ---- KYC ----
    if verification_type in (None, "all", "kyc"):
        kyc_query = (
            select(KYCVerification, Account, User)
            .join(Account, KYCVerification.account_id == Account.id)
            .join(User, Account.user_id == User.id)
        )
        if ver_status:
            kyc_query = kyc_query.where(KYCVerification.status == ver_status)
        if search:
            kyc_query = kyc_query.where(
                or_(
                    User.email.ilike(f"%{search}%"),
                    User.first_name.ilike(f"%{search}%"),
                    User.last_name.ilike(f"%{search}%"),
                )
            )
        kyc_result = await db.execute(kyc_query.order_by(KYCVerification.created_at.desc()))
        for kyc, acc, usr in kyc_result.all():
            results.append({
                "id": str(kyc.id),
                "type": "kyc",
                "account_id": str(kyc.account_id),
                "user_id": str(usr.id),
                "user_email": usr.email,
                "user_name": f"{usr.first_name or ''} {usr.last_name or ''}".strip() or None,
                "status": kyc.status.value,
                "documents_submitted": kyc.documents_submitted,
                "persona_inquiry_id": kyc.persona_inquiry_id,
                "rejection_reason": kyc.rejection_reason,
                "verified_at": kyc.verified_at.isoformat() if kyc.verified_at else None,
                "created_at": kyc.created_at.isoformat() if kyc.created_at else None,
                "updated_at": kyc.updated_at.isoformat() if kyc.updated_at else None,
            })

    # ---- KYB ----
    if verification_type in (None, "all", "kyb"):
        from app.models.kyb import KYBVerification
        kyb_query = (
            select(KYBVerification, Account, User)
            .join(Account, KYBVerification.account_id == Account.id)
            .join(User, Account.user_id == User.id)
        )
        if ver_status:
            kyb_query = kyb_query.where(KYBVerification.status == ver_status)
        if search:
            kyb_query = kyb_query.where(
                or_(
                    User.email.ilike(f"%{search}%"),
                    User.first_name.ilike(f"%{search}%"),
                    User.last_name.ilike(f"%{search}%"),
                )
            )
        kyb_result = await db.execute(kyb_query.order_by(KYBVerification.created_at.desc()))
        for kyb, acc, usr in kyb_result.all():
            results.append({
                "id": str(kyb.id),
                "type": "kyb",
                "account_id": str(kyb.account_id),
                "user_id": str(usr.id),
                "user_email": usr.email,
                "user_name": f"{usr.first_name or ''} {usr.last_name or ''}".strip() or None,
                "status": kyb.status.value,
                "documents_submitted": kyb.documents_submitted,
                "business_name": kyb.business_name,
                "verification_type": kyb.verification_type,
                "rejection_reason": kyb.rejection_reason,
                "verified_at": kyb.verified_at.isoformat() if kyb.verified_at else None,
                "created_at": kyb.created_at.isoformat() if kyb.created_at else None,
                "updated_at": kyb.updated_at.isoformat() if kyb.updated_at else None,
            })

    # Sort combined results by created_at descending
    results.sort(key=lambda x: x["created_at"] or "", reverse=True)

    # Manual pagination on combined results
    total = len(results)
    offset = (page - 1) * page_size
    paginated = results[offset: offset + page_size]

    return {
        "data": paginated,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        },
    }


@router.post("/verifications/kyc/{kyc_id}/approve", response_model=Dict[str, Any])
async def approve_kyc(
    kyc_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve a KYC verification — admin only"""
    result = await db.execute(
        select(KYCVerification).where(KYCVerification.id == kyc_id)
    )
    kyc = result.scalar_one_or_none()
    if not kyc:
        raise NotFoundException("KYC Verification", str(kyc_id))

    if kyc.status == KYCStatus.APPROVED:
        raise BadRequestException("KYC is already approved")

    kyc.status = KYCStatus.APPROVED
    kyc.verified_at = datetime.utcnow()
    kyc.rejection_reason = None
    await db.commit()

    # Notify the user
    try:
        from app.services.notification_service import NotificationService, NotificationType
        await NotificationService.create_notification(
            db=db,
            account_id=kyc.account_id,
            notification_type=NotificationType.KYC_APPROVED,
            title="KYC Verification Approved",
            message="Your identity verification has been approved. You now have full access to the platform.",
        )
    except Exception as e:
        logger.warning(f"Failed to send KYC approval notification: {e}")

    logger.info(f"Admin {current_user.id} approved KYC {kyc_id}")
    return {
        "message": "KYC approved",
        "data": {"id": str(kyc.id), "account_id": str(kyc.account_id), "status": kyc.status.value},
    }


@router.post("/verifications/kyc/{kyc_id}/reject", response_model=Dict[str, Any])
async def reject_kyc(
    kyc_id: UUID,
    body: RejectRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reject a KYC verification with a reason — admin only"""
    result = await db.execute(
        select(KYCVerification).where(KYCVerification.id == kyc_id)
    )
    kyc = result.scalar_one_or_none()
    if not kyc:
        raise NotFoundException("KYC Verification", str(kyc_id))

    if kyc.status == KYCStatus.APPROVED:
        raise BadRequestException("Cannot reject an already approved KYC")

    kyc.status = KYCStatus.REJECTED
    kyc.rejection_reason = body.reason
    kyc.verified_at = None
    await db.commit()

    # Notify the user
    try:
        from app.services.notification_service import NotificationService, NotificationType
        await NotificationService.create_notification(
            db=db,
            account_id=kyc.account_id,
            notification_type=NotificationType.KYC_APPROVED,
            title="KYC Verification Rejected",
            message=f"Your identity verification was rejected. Reason: {body.reason}",
        )
    except Exception as e:
        logger.warning(f"Failed to send KYC rejection notification: {e}")

    logger.info(f"Admin {current_user.id} rejected KYC {kyc_id}. Reason: {body.reason}")
    return {
        "message": "KYC rejected",
        "data": {
            "id": str(kyc.id),
            "account_id": str(kyc.account_id),
            "status": kyc.status.value,
            "rejection_reason": kyc.rejection_reason,
        },
    }


@router.post("/verifications/kyb/{kyb_id}/approve", response_model=Dict[str, Any])
async def approve_kyb(
    kyb_id: UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve a KYB verification — admin only"""
    from app.models.kyb import KYBVerification, KYBStatus

    result = await db.execute(
        select(KYBVerification).where(KYBVerification.id == kyb_id)
    )
    kyb = result.scalar_one_or_none()
    if not kyb:
        raise NotFoundException("KYB Verification", str(kyb_id))

    if kyb.status == KYBStatus.APPROVED:
        raise BadRequestException("KYB is already approved")

    kyb.status = KYBStatus.APPROVED
    kyb.verified_at = datetime.utcnow()
    kyb.rejection_reason = None
    await db.commit()

    try:
        from app.services.notification_service import NotificationService, NotificationType
        await NotificationService.create_notification(
            db=db,
            account_id=kyb.account_id,
            notification_type=NotificationType.KYC_APPROVED,
            title="Business Verification Approved",
            message="Your business verification (KYB) has been approved.",
        )
    except Exception as e:
        logger.warning(f"Failed to send KYB approval notification: {e}")

    logger.info(f"Admin {current_user.id} approved KYB {kyb_id}")
    return {
        "message": "KYB approved",
        "data": {"id": str(kyb.id), "account_id": str(kyb.account_id), "status": kyb.status.value},
    }


@router.post("/verifications/kyb/{kyb_id}/reject", response_model=Dict[str, Any])
async def reject_kyb(
    kyb_id: UUID,
    body: RejectRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reject a KYB verification with a reason — admin only"""
    from app.models.kyb import KYBVerification, KYBStatus

    result = await db.execute(
        select(KYBVerification).where(KYBVerification.id == kyb_id)
    )
    kyb = result.scalar_one_or_none()
    if not kyb:
        raise NotFoundException("KYB Verification", str(kyb_id))

    if kyb.status == KYBStatus.APPROVED:
        raise BadRequestException("Cannot reject an already approved KYB")

    kyb.status = KYBStatus.REJECTED
    kyb.rejection_reason = body.reason
    kyb.verified_at = None
    await db.commit()

    try:
        from app.services.notification_service import NotificationService, NotificationType
        await NotificationService.create_notification(
            db=db,
            account_id=kyb.account_id,
            notification_type=NotificationType.KYC_APPROVED,
            title="Business Verification Rejected",
            message=f"Your business verification (KYB) was rejected. Reason: {body.reason}",
        )
    except Exception as e:
        logger.warning(f"Failed to send KYB rejection notification: {e}")

    logger.info(f"Admin {current_user.id} rejected KYB {kyb_id}. Reason: {body.reason}")
    return {
        "message": "KYB rejected",
        "data": {
            "id": str(kyb.id),
            "account_id": str(kyb.account_id),
            "status": kyb.status.value,
            "rejection_reason": kyb.rejection_reason,
        },
    }


# ==================== ASSETS (admin-wide search) ====================

def _admin_asset_payload(asset: Asset) -> Dict[str, Any]:
    """Build an asset response and attach owner info for admin views."""
    from app.api.v1.assets import build_asset_response

    payload = build_asset_response(asset)

    owner = None
    account = getattr(asset, "account", None)
    if account is not None:
        user = getattr(account, "user", None)
        if user is not None:
            full_name = " ".join(filter(None, [user.first_name, user.last_name])).strip()
            owner = {
                "user_id": str(user.id),
                # Never null: fall back to email for legacy users without a name.
                "name": full_name or user.email,
                "email": user.email,
            }
    payload["owner"] = owner
    return payload


@router.get("/assets", response_model=Dict[str, Any])
async def admin_list_assets(
    search: Optional[str] = Query(None, description="Search by asset code (e.g. AK-01), name, symbol, or description"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List and search every asset across all users — admin only.

    Use `search` to find an asset by its human-readable code (AK-01), name,
    symbol, or description.
    """
    from sqlalchemy import or_, desc
    from sqlalchemy.orm import selectinload

    query = select(Asset).options(
        selectinload(Asset.category),
        selectinload(Asset.photos),
        selectinload(Asset.documents),
        selectinload(Asset.account).selectinload(Account.user),
    )
    count_query = select(func.count(Asset.id))

    if search:
        filter_expr = or_(
            Asset.asset_code.ilike(f"%{search}%"),
            Asset.name.ilike(f"%{search}%"),
            Asset.symbol.ilike(f"%{search}%"),
            Asset.description.ilike(f"%{search}%"),
        )
        query = query.where(filter_expr)
        count_query = count_query.where(filter_expr)

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    result = await db.execute(
        query.order_by(desc(Asset.created_at)).offset(offset).limit(page_size)
    )
    assets = result.scalars().all()

    return {
        "data": [_admin_asset_payload(a) for a in assets],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        },
    }


@router.get("/assets/{asset_code}", response_model=Dict[str, Any])
async def admin_get_asset_by_code(
    asset_code: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single asset by its human-readable code (e.g. AK-01) — admin only.

    Embeds the latest AI review, latest AI appraisal result, documents, and
    value history inline so the admin detail view needs no follow-up calls.
    """
    from sqlalchemy.orm import selectinload
    from app.schemas.asset_extended import AIReviewResponse
    from app.api.v1.assets import serialize_asset_document

    result = await db.execute(
        select(Asset)
        .options(
            selectinload(Asset.category),
            selectinload(Asset.photos),
            selectinload(Asset.documents),
            selectinload(Asset.account).selectinload(Account.user),
            selectinload(Asset.ai_reviews),
            selectinload(Asset.appraisals),
            selectinload(Asset.valuations),
        )
        .where(func.lower(Asset.asset_code) == asset_code.lower())
    )
    asset = result.scalar_one_or_none()

    if not asset:
        raise NotFoundException("Asset", asset_code)

    payload = _admin_asset_payload(asset)

    # --- AI review (read-only verdict shown to admins) ---
    payload["ai_review_status"] = asset.ai_review_status.value if asset.ai_review_status else None
    payload["ai_reviewed_at"] = asset.ai_reviewed_at.isoformat() if asset.ai_reviewed_at else None
    # ai_reviews is ordered desc(created_at) on the model, so [0] is the latest.
    latest_review = asset.ai_reviews[0] if asset.ai_reviews else None
    payload["ai_review"] = (
        AIReviewResponse.model_validate(latest_review).model_dump() if latest_review else None
    )

    # --- Latest AI appraisal result ---
    # appraisals is ordered desc(requested_at); pick the most recent carrying ai_data.
    latest_ai_appraisal = next((a for a in asset.appraisals if a.ai_data), None)
    payload["ai_result"] = latest_ai_appraisal.ai_data if latest_ai_appraisal else None

    # --- Value history (oldest -> newest) ---
    _epoch = datetime.min.replace(tzinfo=timezone.utc)
    value_history = []
    for val in sorted(asset.valuations, key=lambda v: v.valuation_date or _epoch):
        if val.valuation_date is None:
            continue
        value_history.append({
            "date": val.valuation_date.isoformat(),
            "value": float(val.value),
            "currency": val.currency,
        })
    payload["value_history"] = value_history

    # --- Documents (full parity with GET /assets/{id}/documents) ---
    # asset.documents is ordered desc(created_at) on the model.
    payload["documents"] = [serialize_asset_document(doc) for doc in asset.documents]

    return {"data": payload}



# ==================== Admin Marketplace Overview ====================
# System-wide views for the admin marketplace page: admins judge the whole
# marketplace, not a personal portfolio (they have no account/watchlist rows).

_ADMIN_MKT_RANGES = {"7d": 7, "30d": 30, "90d": 90, "1y": 365, "all": None}


@router.get("/marketplace/watchlist-top", response_model=Dict[str, Any])
async def admin_top_watchlisted_listings(
    limit: int = Query(6, ge=1, le=50),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Most-watchlisted listings across ALL users — the admin's 'Your
    Watchlist' card shows what the whole market is watching."""
    from app.api.v1.marketplace import _listing_with_category, _LISTING_ASSET_LOAD
    from app.models.marketplace import WatchlistItem, Offer, OfferStatus

    top_rows = (await db.execute(
        select(WatchlistItem.listing_id, func.count(WatchlistItem.id).label("watchers"))
        .group_by(WatchlistItem.listing_id)
        .order_by(func.count(WatchlistItem.id).desc())
        .limit(limit)
    )).all()
    if not top_rows:
        return {"data": [], "total_watchlisted_listings": 0}

    watcher_counts = {listing_id: watchers for listing_id, watchers in top_rows}

    listings = (await db.execute(
        select(MarketplaceListing)
        .options(_LISTING_ASSET_LOAD)
        .where(MarketplaceListing.id.in_(list(watcher_counts)))
    )).scalars().all()

    pending_counts = {
        listing_id: count
        for listing_id, count in (await db.execute(
            select(Offer.listing_id, func.count(Offer.id))
            .where(Offer.listing_id.in_(list(watcher_counts)),
                   Offer.status == OfferStatus.PENDING)
            .group_by(Offer.listing_id)
        ))
    }

    total_watchlisted = (await db.execute(
        select(func.count(func.distinct(WatchlistItem.listing_id)))
    )).scalar() or 0

    items = [
        {
            **_listing_with_category(l).model_dump(),
            "watchers_count": watcher_counts.get(l.id, 0),
            "pending_offers_count": pending_counts.get(l.id, 0),
        }
        for l in listings
    ]
    items.sort(key=lambda i: i["watchers_count"], reverse=True)

    return {"data": items, "total_watchlisted_listings": total_watchlisted}


@router.get("/marketplace/highlights", response_model=Dict[str, Any])
async def admin_marketplace_highlights(
    time_range: str = Query("30d", description="7d, 30d, 90d, 1y, all"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """System-wide marketplace health for the admin highlights section:
    listing/offer funnel, escrow volume and engagement — whole market,
    not any individual portfolio. Change percentages compare the selected
    period against the equally-long preceding period."""
    from app.models.asset import AssetCategory
    from app.models.marketplace import WatchlistItem, Offer, OfferStatus

    if time_range not in _ADMIN_MKT_RANGES:
        raise BadRequestException(
            f"Invalid time_range. Must be one of: {', '.join(_ADMIN_MKT_RANGES)}")

    days = _ADMIN_MKT_RANGES[time_range]
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=days) if days else None
    prev_start = now - timedelta(days=days * 2) if days else None

    async def count_where(model, *conditions):
        return (await db.execute(
            select(func.count(model.id)).where(*conditions)
        )).scalar() or 0

    def pct_change(current: int, previous: int):
        if previous <= 0:
            return None  # no baseline: UI shows "new" instead of a percentage
        return round((current - previous) / previous * 100, 2)

    # Listings funnel
    listings_total = await count_where(MarketplaceListing)
    listings_by_status = {
        s.value: await count_where(MarketplaceListing, MarketplaceListing.status == s)
        for s in (ListingStatus.ACTIVE, ListingStatus.APPROVED,
                  ListingStatus.PENDING_APPROVAL, ListingStatus.REJECTED,
                  ListingStatus.SUSPENDED, ListingStatus.SOLD)
    }
    listings_new = await count_where(
        MarketplaceListing, MarketplaceListing.created_at >= period_start
    ) if period_start else listings_total
    listings_prev = await count_where(
        MarketplaceListing,
        MarketplaceListing.created_at >= prev_start,
        MarketplaceListing.created_at < period_start,
    ) if period_start else 0

    # Offers funnel
    offers_total = await count_where(Offer)
    offers_pending = await count_where(Offer, Offer.status == OfferStatus.PENDING)
    offers_accepted = await count_where(Offer, Offer.status == OfferStatus.ACCEPTED)
    offers_new = await count_where(
        Offer, Offer.created_at >= period_start) if period_start else offers_total
    offers_prev = await count_where(
        Offer, Offer.created_at >= prev_start, Offer.created_at < period_start,
    ) if period_start else 0

    # Escrow volume (whole-market money movement)
    async def escrow_sum(*conditions):
        return float((await db.execute(
            select(func.coalesce(func.sum(EscrowTransaction.amount), 0)).where(*conditions)
        )).scalar() or 0)

    escrow_conditions = [EscrowTransaction.created_at >= period_start] if period_start else []
    escrow = {
        "funded_volume": await escrow_sum(EscrowTransaction.status == EscrowStatus.FUNDED, *escrow_conditions),
        "released_volume": await escrow_sum(EscrowTransaction.status == EscrowStatus.RELEASED, *escrow_conditions),
        "disputed_count": await count_where(EscrowTransaction, EscrowTransaction.status == EscrowStatus.DISPUTED),
        "currency": "USD",
    }

    # Engagement
    engagement = {
        "watchlist_items": await count_where(WatchlistItem),
        "unique_watchers": (await db.execute(
            select(func.count(func.distinct(WatchlistItem.account_id)))
        )).scalar() or 0,
        "unique_bidders_in_period": (await db.execute(
            select(func.count(func.distinct(Offer.account_id))).where(
                *( [Offer.created_at >= period_start] if period_start else [] ))
        )).scalar() or 0,
    }

    # Category breakdown (listing counts across the whole market)
    category_rows = (await db.execute(
        select(AssetCategory.name, func.count(MarketplaceListing.id))
        .join(Asset, Asset.category_id == AssetCategory.id)
        .join(MarketplaceListing, MarketplaceListing.asset_id == Asset.id)
        .group_by(AssetCategory.name)
        .order_by(func.count(MarketplaceListing.id).desc())
        .limit(8)
    )).all()

    return {
        "time_range": time_range,
        "listings": {
            "total": listings_total,
            **listings_by_status,
            "new_in_period": listings_new,
            "new_change_pct": pct_change(listings_new, listings_prev),
        },
        "offers": {
            "total": offers_total,
            "pending": offers_pending,
            "accepted": offers_accepted,
            "new_in_period": offers_new,
            "new_change_pct": pct_change(offers_new, offers_prev),
        },
        "escrow": escrow,
        "engagement": engagement,
        "top_categories": [
            {"category": name, "listings": count} for name, count in category_rows
        ],
        "generated_at": now.isoformat(),
    }
