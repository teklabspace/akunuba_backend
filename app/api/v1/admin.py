from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User, Role
from app.models.account import Account, AccountType
from app.models.payment import Subscription, SubscriptionStatus
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
    if not has_permission(current_user.role, Permission.MANAGE_USERS):
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

