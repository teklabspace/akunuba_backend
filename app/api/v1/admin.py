from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User, Role
from app.models.account import Account, AccountType
from app.models.payment import Subscription, SubscriptionStatus, SubscriptionPlan
from app.models.kyc import KYCVerification, KYCStatus
from app.models.kyb import KYBVerification, KYBStatus
from app.models.marketplace import MarketplaceListing, ListingStatus, EscrowTransaction, EscrowStatus
from app.models.support import SupportTicket, TicketStatus
from app.models.asset import Asset
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from app.core.permissions import Permission, has_permission
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel

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

    # Subscription info
    subscription_plan = None
    if account:
        sub_result = await db.execute(
            select(Subscription).where(
                Subscription.account_id == account.id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
        sub = sub_result.scalar_one_or_none()
        subscription_plan = sub.plan.value if sub else "free"

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

    # Join subscriptions → accounts → users for search
    query = (
        select(Subscription, Account, User)
        .join(Account, Subscription.account_id == Account.id)
        .join(User, Account.user_id == User.id)
    )
    count_query = (
        select(func.count(Subscription.id))
        .join(Account, Subscription.account_id == Account.id)
        .join(User, Account.user_id == User.id)
    )

    if plan:
        query = query.where(Subscription.plan == plan)
        count_query = count_query.where(Subscription.plan == plan)

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
        data.append({
            "id": str(sub.id),
            "account_id": str(sub.account_id),
            "user_id": str(usr.id),
            "user_email": usr.email,
            "user_name": f"{usr.first_name or ''} {usr.last_name or ''}".strip() or None,
            "plan": sub.plan.value,
            "status": sub.status.value,
            "amount": float(sub.amount),
            "currency": sub.currency,
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
    price = PLAN_PRICES.get(plan_id, {}).get(billing_cycle)
    if price is not None:  # concierge has custom (None) pricing — leave amount as-is
        sub.amount = price
    now = datetime.now(timezone.utc)
    sub.current_period_start = now
    sub.current_period_end = now + (timedelta(days=365) if billing_cycle == "annual" else timedelta(days=30))

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

