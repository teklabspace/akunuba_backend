from fastapi import APIRouter, Depends, HTTPException, status, Request, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from decimal import Decimal
from datetime import datetime, timedelta
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.payment import Subscription, SubscriptionPlan, SubscriptionStatus
from app.integrations.stripe_client import StripeClient
from app.core.exceptions import NotFoundException, BadRequestException, ConflictException
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


class SubscriptionCreate(BaseModel):
    plan: SubscriptionPlan
    discount_code: Optional[str] = None


class SubscriptionResponse(BaseModel):
    id: UUID
    plan: str
    status: str
    amount: Decimal
    currency: str
    current_period_end: Optional[datetime] = None

    class Config:
        from_attributes = True


# Subscription pricing
PLAN_PRICES = {
    SubscriptionPlan.MONTHLY: Decimal("99.00"),
    SubscriptionPlan.ANNUAL: Decimal("990.00"),  # 2 months free
}

DISCOUNT_CODES = {
    "EARLYBIRD": Decimal("10"),  # 10% off
    "ANNUAL20": Decimal("20"),  # 20% off annual
}


@router.post("", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    subscription_data: SubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a subscription"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Check if subscription already exists
    existing_result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    existing = existing_result.scalar_one_or_none()
    
    if existing and existing.status == SubscriptionStatus.ACTIVE:
        raise ConflictException("Active subscription already exists")
    
    # Calculate amount with discount
    base_amount = PLAN_PRICES[subscription_data.plan]
    discount_amount = Decimal("0")
    
    if subscription_data.discount_code:
        discount_percent = DISCOUNT_CODES.get(subscription_data.discount_code.upper())
        if discount_percent:
            discount_amount = (base_amount * discount_percent) / 100
    
    final_amount = base_amount - discount_amount
    
    # Create Stripe subscription
    try:
        # Create or get Stripe customer
        stripe_customer = StripeClient.create_customer(
            email=current_user.email,
            name=f"{current_user.first_name} {current_user.last_name}",
            metadata={"account_id": str(account.id)}
        )
        
        # Create Stripe subscription (using price ID - you'd configure these in Stripe)
        # For now, we'll create a payment intent instead
        stripe_subscription = StripeClient.create_subscription(
            customer_id=stripe_customer["id"],
            price_id="price_monthly" if subscription_data.plan == SubscriptionPlan.MONTHLY else "price_annual",
            metadata={"account_id": str(account.id)}
        )
    except Exception as e:
        logger.error(f"Failed to create Stripe subscription: {e}")
        # Continue without Stripe for now
    
    # Calculate period dates
    now = datetime.utcnow()
    if subscription_data.plan == SubscriptionPlan.MONTHLY:
        period_end = now + timedelta(days=30)
    else:
        period_end = now + timedelta(days=365)
    
    subscription = Subscription(
        account_id=account.id,
        plan=subscription_data.plan,
        status=SubscriptionStatus.ACTIVE,
        amount=final_amount,
        currency="USD",
        stripe_subscription_id=stripe_subscription.get("id") if stripe_subscription else None,
        current_period_start=now,
        current_period_end=period_end,
    )
    
    if existing:
        existing.plan = subscription.plan
        existing.status = SubscriptionStatus.ACTIVE
        existing.amount = final_amount
        existing.current_period_start = now
        existing.current_period_end = period_end
        existing.stripe_subscription_id = subscription.stripe_subscription_id
        subscription = existing
    else:
        db.add(subscription)
    
    await db.commit()
    await db.refresh(subscription)
    
    logger.info(f"Subscription created: {subscription.id}")
    return subscription


@router.get("", response_model=Optional[SubscriptionResponse])
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current subscription"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        return None
    
    # Check if subscription needs renewal
    if subscription.status == SubscriptionStatus.ACTIVE:
        if subscription.current_period_end and subscription.current_period_end < datetime.utcnow():
            subscription.status = SubscriptionStatus.EXPIRED
            await db.commit()
    
    return subscription


@router.post("/cancel")
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel subscription"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise NotFoundException("Subscription", str(account.id))
    
    if subscription.status != SubscriptionStatus.ACTIVE:
        raise BadRequestException("Subscription is not active")
    
    # Cancel in Stripe
    if subscription.stripe_subscription_id:
        try:
            StripeClient.cancel_subscription(subscription.stripe_subscription_id)
        except Exception as e:
            logger.error(f"Failed to cancel Stripe subscription: {e}")
    
    subscription.status = SubscriptionStatus.CANCELLED
    subscription.cancelled_at = datetime.utcnow()
    
    await db.commit()
    
    logger.info(f"Subscription cancelled: {subscription.id}")
    return {"message": "Subscription cancelled successfully"}


@router.post("/renew")
async def renew_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Renew expired subscription"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise NotFoundException("Subscription", str(account.id))
    
    if subscription.status != SubscriptionStatus.EXPIRED:
        raise BadRequestException("Subscription is not expired")
    
    # Calculate new period
    now = datetime.utcnow()
    if subscription.plan == SubscriptionPlan.MONTHLY:
        period_end = now + timedelta(days=30)
    else:
        period_end = now + timedelta(days=365)
    
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_start = now
    subscription.current_period_end = period_end
    
    await db.commit()
    
    logger.info(f"Subscription renewed: {subscription.id}")
    return {"message": "Subscription renewed successfully"}


@router.put("/upgrade", response_model=SubscriptionResponse)
async def upgrade_subscription(
    new_plan: SubscriptionPlan = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upgrade or downgrade subscription"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise NotFoundException("Subscription", str(account.id))
    
    if subscription.status != SubscriptionStatus.ACTIVE:
        raise BadRequestException("Subscription must be active to upgrade/downgrade")
    
    # Calculate prorated amount
    old_amount = PLAN_PRICES[subscription.plan]
    new_amount = PLAN_PRICES[new_plan]
    
    # Calculate days remaining
    days_remaining = (subscription.current_period_end - datetime.utcnow()).days
    total_days = (subscription.current_period_end - subscription.current_period_start).days
    
    # Prorate based on remaining days
    if new_plan == SubscriptionPlan.ANNUAL and subscription.plan == SubscriptionPlan.MONTHLY:
        # Upgrade: charge difference prorated
        prorated_amount = (new_amount / 365 * days_remaining) - (old_amount / 30 * days_remaining)
    else:
        # Downgrade: credit difference
        prorated_amount = (old_amount / 30 * days_remaining) - (new_amount / 365 * days_remaining)
    
    subscription.plan = new_plan
    subscription.amount = new_amount
    
    # Update Stripe subscription if exists
    if subscription.stripe_subscription_id:
        try:
            import stripe
            stripe.Subscription.modify(
                subscription.stripe_subscription_id,
                items=[{
                    "id": stripe.Subscription.retrieve(subscription.stripe_subscription_id).items.data[0].id,
                    "price": "price_annual" if new_plan == SubscriptionPlan.ANNUAL else "price_monthly"
                }],
                proration_behavior="always_invoice"
            )
        except Exception as e:
            logger.error(f"Failed to update Stripe subscription: {e}")
    
    await db.commit()
    await db.refresh(subscription)
    
    logger.info(f"Subscription upgraded/downgraded: {subscription.id}")
    return subscription


@router.get("/history")
async def get_subscription_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get subscription history and payment records"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        return {"subscription": None, "payments": []}
    
    # Get related payments
    from app.models.payment import Payment, PaymentStatus
    payments_result = await db.execute(
        select(Payment).where(
            Payment.account_id == account.id,
            Payment.status == PaymentStatus.COMPLETED
        ).order_by(Payment.created_at.desc())
    )
    payments = payments_result.scalars().all()
    
    return {
        "subscription": {
            "id": subscription.id,
            "plan": subscription.plan.value,
            "status": subscription.status.value,
            "amount": float(subscription.amount),
            "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
        },
        "payments": [
            {
                "id": str(payment.id),
                "amount": float(payment.amount),
                "currency": payment.currency,
                "created_at": payment.created_at.isoformat()
            }
            for payment in payments
        ]
    }


@router.post("/webhook")
async def subscription_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle Stripe subscription webhook events"""
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    
    try:
        event = StripeClient.verify_webhook_signature(payload, signature)
        if not event:
            raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"Webhook verification failed: {e}")
        raise HTTPException(status_code=400, detail="Webhook verification failed")
    
    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})
    
    if event_type == "customer.subscription.updated":
        subscription_id = data.get("id")
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == subscription_id)
        )
        subscription = result.scalar_one_or_none()
        
        if subscription:
            status = data.get("status")
            if status == "active":
                subscription.status = SubscriptionStatus.ACTIVE
            elif status == "canceled":
                subscription.status = SubscriptionStatus.CANCELLED
            elif status == "past_due":
                subscription.status = SubscriptionStatus.PAST_DUE
            
            subscription.current_period_start = datetime.fromtimestamp(data.get("current_period_start", 0))
            subscription.current_period_end = datetime.fromtimestamp(data.get("current_period_end", 0))
            await db.commit()
            logger.info(f"Subscription updated via webhook: {subscription.id}")
    
    elif event_type == "customer.subscription.deleted":
        subscription_id = data.get("id")
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == subscription_id)
        )
        subscription = result.scalar_one_or_none()
        
        if subscription:
            subscription.status = SubscriptionStatus.CANCELLED
            subscription.cancelled_at = datetime.utcnow()
            await db.commit()
            logger.info(f"Subscription cancelled via webhook: {subscription.id}")
    
    return {"status": "success"}


@router.get("/permissions")
async def get_subscription_permissions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user subscription permissions and limits"""
    from app.api.deps import get_account, get_user_subscription_plan
    from app.core.features import get_permissions, get_plan_limits
    
    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)
    
    permissions = get_permissions(plan)
    limits = get_plan_limits(plan)
    
    result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    subscription = result.scalar_one_or_none()
    
    return {
        "plan": plan.value,
        "status": subscription.status.value if subscription else "none",
        "permissions": permissions,
        "limits": limits,
        "current_period_end": subscription.current_period_end.isoformat() if subscription and subscription.current_period_end else None
    }


@router.get("/limits")
async def get_usage_limits(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current usage and limits for user's subscription"""
    from app.api.deps import get_account, get_user_subscription_plan
    from app.core.features import get_plan_limits
    from sqlalchemy import select, func
    from app.models.asset import Asset
    from app.models.document import Document
    from app.models.marketplace import MarketplaceListing, Offer, ListingStatus, OfferStatus
    
    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)
    limits = get_plan_limits(plan)
    
    # Get current usage
    assets_count = await db.execute(
        select(func.count(Asset.id)).where(Asset.account_id == account.id)
    )
    assets_used = assets_count.scalar() or 0
    
    documents_count = await db.execute(
        select(func.count(Document.id)).where(Document.account_id == account.id)
    )
    documents_used = documents_count.scalar() or 0
    
    listings_count = await db.execute(
        select(func.count(MarketplaceListing.id)).where(
            MarketplaceListing.account_id == account.id,
            MarketplaceListing.status == ListingStatus.ACTIVE
        )
    )
    listings_used = listings_count.scalar() or 0
    
    offers_count = await db.execute(
        select(func.count(Offer.id)).where(
            Offer.account_id == account.id,
            Offer.status == OfferStatus.PENDING
        )
    )
    offers_used = offers_count.scalar() or 0
    
    return {
        "plan": plan.value,
        "limits": limits,
        "usage": {
            "assets": assets_used,
            "documents": documents_used,
            "listings": listings_used,
            "offers": offers_used,
        },
        "remaining": {
            "assets": limits.get("assets") - assets_used if limits.get("assets") else None,
            "documents": limits.get("documents") - documents_used if limits.get("documents") else None,
            "listings": limits.get("listings") - listings_used if limits.get("listings") else None,
            "offers": limits.get("offers") - offers_used if limits.get("offers") else None,
        }
    }

