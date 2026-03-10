from fastapi import APIRouter, Depends, HTTPException, status, Request, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import json
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


# Plan definitions matching the spec
PLANS_CONFIG = {
    "plan_starter": {
        "id": "plan_starter",
        "name": "Starter",
        "description": "Perfect for new or casual investors",
        "monthly_price": Decimal("0.00"),
        "annual_price": Decimal("0.00"),
        "currency": "USD",
        "features": [
            "Basic portfolio dashboard",
            "Limited aggregation (1-2 accounts)",
            "Read-only market performance",
            "Marketplace browsing",
            "Standard email support"
        ],
        "limits": {
            "max_accounts": 2,
            "max_assets": 10
        },
        "popular": False,
        "is_custom": False
    },
    "plan_pro": {
        "id": "plan_pro",
        "name": "Pro",
        "description": "For active investors & small business owners",
        "monthly_price": Decimal("199.00"),
        "annual_price": Decimal("1999.00"),
        "currency": "USD",
        "features": [
            "Full portfolio management",
            "Automated rebalancing",
            "Marketplace access",
            "Asset valuation tools",
            "Transaction tracking",
            "Priority support"
        ],
        "limits": {
            "max_accounts": 10,
            "max_assets": 100
        },
        "popular": True,
        "is_custom": False
    },
    "plan_premium": {
        "id": "plan_premium",
        "name": "Premium",
        "description": "For advanced investors & entrepreneurs",
        "monthly_price": Decimal("699.00"),
        "annual_price": Decimal("6999.00"),
        "currency": "USD",
        "features": [
            "Everything in Pro",
            "AI-driven insights",
            "Automated asset valuation",
            "Document center",
            "Tax & investment advisory",
            "Premium support"
        ],
        "limits": {
            "max_accounts": -1,
            "max_assets": -1
        },
        "popular": False,
        "is_custom": False
    },
    "plan_concierge": {
        "id": "plan_concierge",
        "name": "Concierge",
        "description": "Custom enterprise solution",
        "monthly_price": None,
        "annual_price": None,
        "currency": "USD",
        "features": [
            "Everything in Premium",
            "Dedicated account manager",
            "Custom integrations",
            "White-glove onboarding",
            "24/7 concierge support"
        ],
        "limits": {
            "max_accounts": -1,
            "max_assets": -1
        },
        "popular": False,
        "is_custom": True
    }
}


class SubscriptionCreate(BaseModel):
    plan_id: str
    billing_cycle: str
    payment_method_id: Optional[str] = None
    coupon_code: Optional[str] = None


class PlanResponse(BaseModel):
    id: str
    name: str
    description: str
    monthly_price: Optional[Decimal]
    annual_price: Optional[Decimal]
    currency: str
    features: List[str]
    limits: Dict[str, int]
    popular: bool
    is_custom: Optional[bool] = False


class PlansResponse(BaseModel):
    plans: List[PlanResponse]


class SubscriptionResponse(BaseModel):
    id: UUID
    plan_id: str
    plan_name: str
    status: str
    amount: Decimal
    currency: str
    billing_cycle: str
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    canceled_at: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    features: Optional[List[str]] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PaymentIntentResponse(BaseModel):
    id: str
    client_secret: str
    status: str
    amount: Decimal
    currency: str


class SubscriptionCreateResponse(BaseModel):
    subscription: SubscriptionResponse
    payment_intent: Optional[PaymentIntentResponse] = None


# Subscription pricing (mapping from plan_id to prices)
PLAN_PRICES = {
    "plan_starter": {"monthly": Decimal("0.00"), "annual": Decimal("0.00")},
    "plan_pro": {"monthly": Decimal("199.00"), "annual": Decimal("1999.00")},
    "plan_premium": {"monthly": Decimal("699.00"), "annual": Decimal("6999.00")},
    "plan_concierge": {"monthly": None, "annual": None},
}

# Map plan_id to internal SubscriptionPlan enum
PLAN_ID_TO_ENUM = {
    "plan_starter": SubscriptionPlan.FREE,
    "plan_pro": SubscriptionPlan.MONTHLY,
    "plan_premium": SubscriptionPlan.ANNUAL,
    "plan_concierge": SubscriptionPlan.ANNUAL,  # Map concierge to annual for now
}

DISCOUNT_CODES = {
    "EARLYBIRD": Decimal("10"),  # 10% off
    "ANNUAL20": Decimal("20"),  # 20% off annual
}


@router.get("/plans", response_model=PlansResponse)
async def get_available_plans(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all available subscription plans with pricing, features, and limits"""
    plans = [PlanResponse(**plan_config) for plan_config in PLANS_CONFIG.values()]
    return PlansResponse(plans=plans)


@router.post("", response_model=SubscriptionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    subscription_data: SubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create/activate a subscription"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Validate plan_id
    if subscription_data.plan_id not in PLANS_CONFIG:
        raise BadRequestException("Invalid plan_id provided")
    
    plan_config = PLANS_CONFIG[subscription_data.plan_id]
    
    # Validate billing_cycle
    if subscription_data.billing_cycle not in ["monthly", "annual"]:
        raise BadRequestException("billing_cycle must be 'monthly' or 'annual'")
    
    # Get price based on billing cycle
    if subscription_data.billing_cycle == "monthly":
        base_amount = plan_config["monthly_price"]
    else:
        base_amount = plan_config["annual_price"]
    
    if base_amount is None:
        raise BadRequestException("This plan requires custom pricing. Please contact support.")
    
    # Calculate amount with discount
    discount_amount = Decimal("0")
    if subscription_data.coupon_code:
        discount_percent = DISCOUNT_CODES.get(subscription_data.coupon_code.upper())
        if discount_percent:
            discount_amount = (base_amount * discount_percent) / 100
    
    final_amount = base_amount - discount_amount
    
    # Check if subscription already exists
    existing_result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    existing = existing_result.scalar_one_or_none()
    
    # Map plan_id to internal enum
    internal_plan = PLAN_ID_TO_ENUM.get(subscription_data.plan_id, SubscriptionPlan.FREE)
    
    # Create payment intent via Stripe
    payment_intent = None
    try:
        # Create or get Stripe customer
        stripe_customer = StripeClient.create_customer(
            email=current_user.email,
            name=f"{current_user.first_name} {current_user.last_name}",
            metadata={"account_id": str(account.id)}
        )
        
        # Create payment intent
        stripe_payment_intent = StripeClient.create_payment_intent(
            amount=int(final_amount * 100),  # Convert to cents
            currency="usd",
            metadata={
                "account_id": str(account.id),
                "user_id": str(current_user.id),
                "plan_id": subscription_data.plan_id,
                "billing_cycle": subscription_data.billing_cycle
            }
        )
        
        payment_intent = PaymentIntentResponse(
            id=stripe_payment_intent["id"],
            client_secret=stripe_payment_intent["client_secret"],
            status=stripe_payment_intent["status"],
            amount=final_amount,
            currency="USD"
        )
    except Exception as e:
        logger.error(f"Failed to create Stripe payment intent: {e}")
        # Return 402 if payment is required
        if final_amount > 0:
            raise HTTPException(
                status_code=402,
                detail="Payment method required",
                headers={"payment_intent": json.dumps({
                    "id": "pi_xxx",
                    "client_secret": "pi_xxx_secret_xxx"
                })}
            )
    
    # Calculate period dates
    now = datetime.now(timezone.utc)
    if subscription_data.billing_cycle == "monthly":
        period_end = now + timedelta(days=30)
    else:
        period_end = now + timedelta(days=365)
    
    # Create or update subscription
    if existing:
        existing.plan = internal_plan
        existing.status = SubscriptionStatus.ACTIVE
        existing.amount = final_amount
        existing.current_period_start = now
        existing.current_period_end = period_end
        subscription = existing
    else:
        subscription = Subscription(
            account_id=account.id,
            plan=internal_plan,
            status=SubscriptionStatus.ACTIVE,
            amount=final_amount,
            currency="USD",
            current_period_start=now,
            current_period_end=period_end,
        )
        db.add(subscription)
    
    await db.commit()
    await db.refresh(subscription)
    
    # Build response
    subscription_response = SubscriptionResponse(
        id=subscription.id,
        plan_id=subscription_data.plan_id,
        plan_name=plan_config["name"],
        status=subscription.status.value,
        amount=subscription.amount,
        currency=subscription.currency,
        billing_cycle=subscription_data.billing_cycle,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=False,
        canceled_at=subscription.cancelled_at,
        features=plan_config["features"],
        created_at=subscription.created_at
    )
    
    logger.info(f"Subscription created: {subscription.id}")
    return SubscriptionCreateResponse(
        subscription=subscription_response,
        payment_intent=payment_intent
    )


@router.get("", response_model=Optional[SubscriptionResponse])
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current subscription status"""
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
    now = datetime.now(timezone.utc)
    if subscription.status == SubscriptionStatus.ACTIVE:
        if subscription.current_period_end:
            # Ensure timezone-aware comparison
            period_end = subscription.current_period_end
            if period_end.tzinfo is None:
                period_end = period_end.replace(tzinfo=timezone.utc)
            if period_end < now:
                subscription.status = SubscriptionStatus.EXPIRED
                await db.commit()
    
    # Map internal plan to plan_id
    plan_id_map = {v: k for k, v in PLAN_ID_TO_ENUM.items()}
    plan_id = plan_id_map.get(subscription.plan, "plan_starter")
    plan_config = PLANS_CONFIG.get(plan_id, PLANS_CONFIG["plan_starter"])
    
    # Determine billing cycle from period length
    billing_cycle = "monthly"
    if subscription.current_period_start and subscription.current_period_end:
        days = (subscription.current_period_end - subscription.current_period_start).days
        if days > 60:  # Annual is ~365 days
            billing_cycle = "annual"
    
    return SubscriptionResponse(
        id=subscription.id,
        plan_id=plan_id,
        plan_name=plan_config["name"],
        status=subscription.status.value,
        amount=subscription.amount,
        currency=subscription.currency,
        billing_cycle=billing_cycle,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=False,  # TODO: Add this field to model
        canceled_at=subscription.cancelled_at,
        features=plan_config["features"],
        created_at=subscription.created_at
    )


class CancelSubscriptionRequest(BaseModel):
    cancel_immediately: bool = False
    cancellation_reason: Optional[str] = None


@router.post("/cancel")
async def cancel_subscription(
    cancel_data: Optional[CancelSubscriptionRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel the current active subscription"""
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
        raise BadRequestException("No active subscription to cancel")
    
    if subscription.status != SubscriptionStatus.ACTIVE:
        raise BadRequestException("No active subscription to cancel")
    
    cancel_immediately = cancel_data.cancel_immediately if cancel_data else False
    cancellation_reason = cancel_data.cancellation_reason if cancel_data else None
    
    # Cancel in Stripe
    if subscription.stripe_subscription_id:
        try:
            StripeClient.cancel_subscription(subscription.stripe_subscription_id, cancel_immediately)
        except Exception as e:
            logger.error(f"Failed to cancel Stripe subscription: {e}")
    
    if cancel_immediately:
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = datetime.now(timezone.utc)
        message = "Subscription cancelled immediately"
    else:
        # Mark to cancel at period end
        subscription.cancelled_at = datetime.now(timezone.utc)
        # TODO: Add cancel_at_period_end field to model
        period_end_str = subscription.current_period_end.isoformat() if subscription.current_period_end else "end of period"
        message = f"Subscription will remain active until {period_end_str}"
    
    await db.commit()
    await db.refresh(subscription)
    
    # Map to response format
    plan_id_map = {v: k for k, v in PLAN_ID_TO_ENUM.items()}
    plan_id = plan_id_map.get(subscription.plan, "plan_starter")
    plan_config = PLANS_CONFIG.get(plan_id, PLANS_CONFIG["plan_starter"])
    
    subscription_response = {
        "id": str(subscription.id),
        "status": subscription.status.value,
        "cancel_at_period_end": not cancel_immediately,
        "canceled_at": subscription.cancelled_at.isoformat() if subscription.cancelled_at else None,
        "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
        "cancellation_reason": cancellation_reason
    }
    
    logger.info(f"Subscription cancelled: {subscription.id}")
    return {
        "subscription": subscription_response,
        "message": message
    }


@router.post("/renew")
async def renew_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Renew an expired or canceled subscription"""
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
    
    if subscription.status == SubscriptionStatus.ACTIVE:
        raise BadRequestException("Subscription is already active")
    
    # Determine billing cycle from previous period
    now = datetime.now(timezone.utc)
    if subscription.current_period_start and subscription.current_period_end:
        days = (subscription.current_period_end - subscription.current_period_start).days
        if days > 60:
            period_end = now + timedelta(days=365)
            billing_cycle = "annual"
        else:
            period_end = now + timedelta(days=30)
            billing_cycle = "monthly"
    else:
        # Default to monthly if no previous period
        period_end = now + timedelta(days=30)
        billing_cycle = "monthly"
    
    # Check if payment is required
    plan_id_map = {v: k for k, v in PLAN_ID_TO_ENUM.items()}
    plan_id = plan_id_map.get(subscription.plan, "plan_starter")
    plan_config = PLANS_CONFIG.get(plan_id, PLANS_CONFIG["plan_starter"])
    
    if billing_cycle == "monthly":
        renewal_amount = plan_config["monthly_price"]
    else:
        renewal_amount = plan_config["annual_price"]
    
    payment_intent = None
    if renewal_amount and renewal_amount > 0:
        try:
            stripe_customer = StripeClient.create_customer(
                email=current_user.email,
                name=f"{current_user.first_name} {current_user.last_name}",
                metadata={"account_id": str(account.id)}
            )
            
            stripe_payment_intent = StripeClient.create_payment_intent(
                amount=int(renewal_amount * 100),
                currency="usd",
                metadata={
                    "account_id": str(account.id),
                    "subscription_id": str(subscription.id),
                    "action": "renewal"
                }
            )
            
            payment_intent = {
                "id": stripe_payment_intent["id"],
                "client_secret": stripe_payment_intent["client_secret"]
            }
        except Exception as e:
            logger.error(f"Failed to create payment intent for renewal: {e}")
            raise HTTPException(
                status_code=402,
                detail="Payment method required for renewal",
                headers={"payment_intent": json.dumps(payment_intent) if payment_intent else "{}"}
            )
    
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_start = now
    subscription.current_period_end = period_end
    subscription.amount = renewal_amount if renewal_amount else subscription.amount
    
    await db.commit()
    await db.refresh(subscription)
    
    # Build response
    subscription_response = SubscriptionResponse(
        id=subscription.id,
        plan_id=plan_id,
        plan_name=plan_config["name"],
        status=subscription.status.value,
        amount=subscription.amount,
        currency=subscription.currency,
        billing_cycle=billing_cycle,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        created_at=subscription.created_at
    )
    
    logger.info(f"Subscription renewed: {subscription.id}")
    return {
        "subscription": subscription_response,
        "message": "Subscription renewed successfully"
    }


class UpgradeSubscriptionRequest(BaseModel):
    plan_id: Optional[str] = None
    billing_cycle: Optional[str] = None


@router.put("/upgrade")
async def upgrade_subscription(
    upgrade_data: UpgradeSubscriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upgrade/downgrade subscription plan or billing cycle"""
    if not upgrade_data.plan_id and not upgrade_data.billing_cycle:
        raise BadRequestException("At least one of plan_id or billing_cycle must be provided")
    
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
    
    # Get current plan info
    plan_id_map = {v: k for k, v in PLAN_ID_TO_ENUM.items()}
    current_plan_id = plan_id_map.get(subscription.plan, "plan_starter")
    current_plan_config = PLANS_CONFIG.get(current_plan_id, PLANS_CONFIG["plan_starter"])
    
    # Determine new plan_id
    new_plan_id = upgrade_data.plan_id if upgrade_data.plan_id else current_plan_id
    if new_plan_id not in PLANS_CONFIG:
        raise BadRequestException("Invalid plan_id provided")
    
    new_plan_config = PLANS_CONFIG[new_plan_id]
    
    # Determine new billing cycle
    if subscription.current_period_start and subscription.current_period_end:
        days = (subscription.current_period_end - subscription.current_period_start).days
        current_billing_cycle = "annual" if days > 60 else "monthly"
    else:
        current_billing_cycle = "monthly"
    
    new_billing_cycle = upgrade_data.billing_cycle if upgrade_data.billing_cycle else current_billing_cycle
    if new_billing_cycle not in ["monthly", "annual"]:
        raise BadRequestException("billing_cycle must be 'monthly' or 'annual'")
    
    # Get prices
    if new_billing_cycle == "monthly":
        new_amount = new_plan_config["monthly_price"]
    else:
        new_amount = new_plan_config["annual_price"]
    
    if new_amount is None:
        raise BadRequestException("This plan requires custom pricing. Please contact support.")
    
    # Calculate prorated amount
    now = datetime.now(timezone.utc)
    if subscription.current_period_end:
        period_end = subscription.current_period_end
        if period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=timezone.utc)
        days_remaining = (period_end - now).days
        total_days = (subscription.current_period_end - subscription.current_period_start).days if subscription.current_period_start else 30
        
        if current_billing_cycle == "monthly":
            old_daily_rate = float(current_plan_config["monthly_price"] or 0) / 30
        else:
            old_daily_rate = float(current_plan_config["annual_price"] or 0) / 365
        
        if new_billing_cycle == "monthly":
            new_daily_rate = float(new_amount) / 30
        else:
            new_daily_rate = float(new_amount) / 365
        
        prorated_amount = Decimal(str((new_daily_rate - old_daily_rate) * days_remaining))
    else:
        prorated_amount = Decimal("0.00")
    
    # Map to internal plan enum
    new_internal_plan = PLAN_ID_TO_ENUM.get(new_plan_id, SubscriptionPlan.FREE)
    
    # Calculate new period end
    if new_billing_cycle == "monthly":
        new_period_end = now + timedelta(days=30)
    else:
        new_period_end = now + timedelta(days=365)
    
    # Create payment intent if upgrade requires payment
    payment_intent = None
    if prorated_amount > 0:
        try:
            stripe_customer = StripeClient.create_customer(
                email=current_user.email,
                name=f"{current_user.first_name} {current_user.last_name}",
                metadata={"account_id": str(account.id)}
            )
            
            stripe_payment_intent = StripeClient.create_payment_intent(
                amount=int(prorated_amount * 100),
                currency="usd",
                metadata={
                    "account_id": str(account.id),
                    "subscription_id": str(subscription.id),
                    "action": "upgrade",
                    "new_plan_id": new_plan_id
                }
            )
            
            payment_intent = {
                "id": stripe_payment_intent["id"],
                "client_secret": stripe_payment_intent["client_secret"],
                "amount": float(prorated_amount)
            }
        except Exception as e:
            logger.error(f"Failed to create payment intent for upgrade: {e}")
            raise HTTPException(
                status_code=402,
                detail="Payment required for plan upgrade",
                headers={"payment_intent": json.dumps(payment_intent) if payment_intent else "{}"}
            )
    
    # Update subscription
    subscription.plan = new_internal_plan
    subscription.amount = new_amount
    subscription.current_period_start = now
    subscription.current_period_end = new_period_end
    
    await db.commit()
    await db.refresh(subscription)
    
    # Build response
    subscription_response = SubscriptionResponse(
        id=subscription.id,
        plan_id=new_plan_id,
        plan_name=new_plan_config["name"],
        status=subscription.status.value,
        amount=subscription.amount,
        currency=subscription.currency,
        billing_cycle=new_billing_cycle,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        created_at=subscription.created_at
    )
    
    logger.info(f"Subscription upgraded/downgraded: {subscription.id}")
    return {
        "subscription": subscription_response,
        "message": "Subscription updated successfully"
    }


@router.get("/history")
async def get_subscription_history(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get subscription history"""
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 20
    if offset < 0:
        offset = 0
    
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
        .order_by(Subscription.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    subscriptions = result.scalars().all()
    
    # Map internal plan to plan_id
    plan_id_map = {v: k for k, v in PLAN_ID_TO_ENUM.items()}
    
    data = []
    for subscription in subscriptions:
        plan_id = plan_id_map.get(subscription.plan, "plan_starter")
        plan_config = PLANS_CONFIG.get(plan_id, PLANS_CONFIG["plan_starter"])
        
        # Determine billing cycle
        billing_cycle = "monthly"
        if subscription.current_period_start and subscription.current_period_end:
            days = (subscription.current_period_end - subscription.current_period_start).days
            if days > 60:
                billing_cycle = "annual"
        
        data.append({
            "id": str(subscription.id),
            "plan_id": plan_id,
            "plan_name": plan_config["name"],
            "status": subscription.status.value,
            "amount": float(subscription.amount),
            "currency": subscription.currency,
            "billing_cycle": billing_cycle,
            "period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            "period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            "created_at": subscription.created_at.isoformat() if subscription.created_at else None,
        })
    
    # Get total count
    total_result = await db.execute(
        select(func.count(Subscription.id)).where(Subscription.account_id == account.id)
    )
    total = total_result.scalar() or 0
    
    return {
        "data": data,
        "total": total,
        "limit": limit,
        "offset": offset
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
    """Get feature permissions and access levels for the current user's subscription"""
    from app.api.deps import get_account, get_user_subscription_plan
    from app.core.features import get_permissions, get_plan_limits, get_plan_features, Feature
    
    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)
    
    permissions_dict = get_permissions(plan)
    limits = get_plan_limits(plan)
    plan_features = get_plan_features(plan)
    
    # Map to spec format
    features_dict = {
        "portfolio_management": Feature.PORTFOLIO_BASIC in plan_features or Feature.PORTFOLIO_ADVANCED in plan_features,
        "marketplace_access": Feature.MARKETPLACE_BROWSE in plan_features,
        "marketplace_listing": Feature.MARKETPLACE_LIST in plan_features,
        "marketplace_purchase": Feature.MARKETPLACE_OFFER in plan_features,
        "asset_valuation": Feature.ASSETS_VIEW in plan_features,
        "automated_rebalancing": Feature.PORTFOLIO_ADVANCED in plan_features,
        "ai_insights": Feature.ANALYTICS_ADVANCED in plan_features,
        "document_center": Feature.DOCUMENTS_UNLIMITED in plan_features,
        "tax_advisory": False,  # Not in current feature set
        "priority_support": Feature.SUPPORT_PRIORITY in plan_features,
        "concierge_support": False,  # Only for concierge plan
    }
    
    # Map limits to spec format
    limits_dict = {
        "max_accounts": limits.get("accounts", -1) if limits.get("accounts") is not None else -1,
        "max_assets": limits.get("assets", -1) if limits.get("assets") is not None else -1,
        "max_marketplace_listings": limits.get("listings", -1) if limits.get("listings") is not None else -1,
    }
    
    return {
        "features": features_dict,
        "limits": limits_dict
    }


@router.get("/limits")
async def get_usage_limits(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current usage vs. plan limits"""
    from app.api.deps import get_account, get_user_subscription_plan
    from app.core.features import get_plan_limits
    from sqlalchemy import select, func
    from app.models.asset import Asset
    from app.models.marketplace import MarketplaceListing, ListingStatus
    
    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)
    limits = get_plan_limits(plan)
    
    # Get current usage
    assets_count = await db.execute(
        select(func.count(Asset.id)).where(Asset.account_id == account.id)
    )
    assets_used = assets_count.scalar() or 0
    
    listings_count = await db.execute(
        select(func.count(MarketplaceListing.id)).where(
            MarketplaceListing.account_id == account.id,
            MarketplaceListing.status == ListingStatus.ACTIVE
        )
    )
    listings_used = listings_count.scalar() or 0
    
    # Count linked accounts (banking accounts)
    from app.models.banking import LinkedAccount
    accounts_count = await db.execute(
        select(func.count(LinkedAccount.id)).where(
            LinkedAccount.account_id == account.id,
            LinkedAccount.is_active == True
        )
    )
    accounts_used = accounts_count.scalar() or 0
    
    # Map limits to spec format
    max_accounts = limits.get("accounts", -1) if limits.get("accounts") is not None else -1
    max_assets = limits.get("assets", -1) if limits.get("assets") is not None else -1
    max_listings = limits.get("listings", -1) if limits.get("listings") is not None else -1
    
    limits_dict = {
        "max_accounts": max_accounts,
        "max_assets": max_assets,
        "max_marketplace_listings": max_listings,
    }
    
    usage_dict = {
        "accounts": accounts_used,
        "assets": assets_used,
        "marketplace_listings": listings_used,
    }
    
    # Calculate percentages
    percentages_dict = {}
    if max_accounts > 0:
        percentages_dict["accounts"] = int((accounts_used / max_accounts) * 100)
    else:
        percentages_dict["accounts"] = 0
    
    if max_assets > 0:
        percentages_dict["assets"] = int((assets_used / max_assets) * 100)
    else:
        percentages_dict["assets"] = 0
    
    if max_listings > 0:
        percentages_dict["marketplace_listings"] = int((listings_used / max_listings) * 100)
    else:
        percentages_dict["marketplace_listings"] = 0
    
    return {
        "limits": limits_dict,
        "usage": usage_dict,
        "percentages": percentages_dict
    }

