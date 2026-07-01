from fastapi import APIRouter, Depends, HTTPException, status, Request, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import json
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User, Role
from app.models.account import Account
from app.models.payment import Subscription, SubscriptionPlan, SubscriptionStatus
from app.models.kyc import KYCVerification, KYCStatus
from app.integrations.stripe_client import StripeClient
from app.core.exceptions import NotFoundException, BadRequestException, ConflictException, ForbiddenException
from app.core.responses import success_envelope
from app.core.rate_limit import limiter
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


# Plan definitions matching the spec
PLANS_CONFIG = {
    "starter": {
        "id": "starter",
        "name": "Starter",
        "description": "Perfect for new or casual investors",
        "monthly_price": Decimal("49.00"),
        "annual_price": Decimal("470.00"),
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
    "pro": {
        "id": "pro",
        "name": "Pro",
        "description": "For active investors & small business owners",
        "monthly_price": Decimal("299.00"),
        "annual_price": Decimal("2870.00"),
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
    "premium": {
        "id": "premium",
        "name": "Premium",
        "description": "For advanced investors & entrepreneurs",
        "monthly_price": Decimal("899.00"),
        "annual_price": Decimal("8630.00"),
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
    }
}


class SubscriptionCreate(BaseModel):
    plan_id: str
    billing_cycle: str
    payment_method_id: Optional[str] = None


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
    # Surfaced at the top level so the frontend can trigger Stripe 3DS without
    # digging into the nested payment_intent object.
    requires_action: bool = False
    client_secret: Optional[str] = None


# Subscription pricing (mapping from plan_id to prices).
# Annual = ~20% off 12x the monthly price.
PLAN_PRICES = {
    "starter": {"monthly": Decimal("49.00"), "annual": Decimal("470.00")},
    "pro": {"monthly": Decimal("299.00"), "annual": Decimal("2870.00")},
    "premium": {"monthly": Decimal("899.00"), "annual": Decimal("8630.00")},
}

# Map plan_id to internal SubscriptionPlan enum
PLAN_ID_TO_ENUM = {
    "starter": SubscriptionPlan.FREE,
    "pro": SubscriptionPlan.MONTHLY,
    "premium": SubscriptionPlan.ANNUAL,
}

PLAN_ENUM_TO_ID = {
    SubscriptionPlan.FREE: "starter",
    SubscriptionPlan.MONTHLY: "pro",
    SubscriptionPlan.ANNUAL: "premium",
}


def normalize_plan_id(plan_id: Optional[str]) -> Optional[str]:
    """Accept both bare IDs (e.g. 'starter') and legacy 'plan_'-prefixed IDs
    (e.g. 'plan_starter') for backward compatibility during the frontend migration."""
    if not plan_id:
        return plan_id
    if plan_id in PLANS_CONFIG:
        return plan_id
    if plan_id.startswith("plan_") and plan_id[len("plan_"):] in PLANS_CONFIG:
        return plan_id[len("plan_"):]
    return plan_id


def get_plan_tier(subscription: Subscription) -> str:
    """The product tier the user actually bought ("starter" | "pro" | "premium").

    Prefer the explicit ``plan_tier`` column; fall back to reverse-mapping the
    legacy ``plan`` enum for rows written before that column existed.
    """
    if getattr(subscription, "plan_tier", None):
        return subscription.plan_tier
    return PLAN_ENUM_TO_ID.get(subscription.plan, "starter")


def get_billing_cycle(subscription: Subscription) -> str:
    """The billing cycle ("monthly" | "annual").

    Prefer the explicit ``billing_cycle`` column; fall back to inferring it from
    the period length for legacy rows.
    """
    if getattr(subscription, "billing_cycle", None):
        return subscription.billing_cycle
    if subscription.current_period_start and subscription.current_period_end:
        if (subscription.current_period_end - subscription.current_period_start).days > 60:
            return "annual"
    return "monthly"


def is_email_verified(user: User) -> bool:
    """A user's email counts as verified via either the boolean flag or a recorded
    verification timestamp."""
    return bool(user.is_verified or user.email_verified_at)


async def is_kyc_approved(db: AsyncSession, account_id: UUID) -> bool:
    """True only when the account's Persona (KYC) verification is approved."""
    result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account_id)
    )
    kyc = result.scalar_one_or_none()
    return bool(kyc and kyc.status == KYCStatus.APPROVED)


async def assert_can_purchase(user: User, account: Account, db: AsyncSession) -> None:
    """Enforce who may buy a plan: only an investor whose email AND Persona (KYC)
    verification are both complete. Raises a 403 with a specific code otherwise."""
    if user.role in (Role.ADMIN, Role.ADVISOR):
        raise ForbiddenException(
            "Your account does not require a subscription.",
            code="SUBSCRIPTION_NOT_APPLICABLE",
        )
    if not is_email_verified(user):
        raise ForbiddenException(
            "Verify your email before purchasing a plan.",
            code="EMAIL_NOT_VERIFIED",
        )
    if not await is_kyc_approved(db, account.id):
        raise ForbiddenException(
            "Complete identity verification (Persona) before purchasing a plan.",
            code="KYC_NOT_APPROVED",
        )


async def build_capabilities(
    user: User,
    account: Optional[Account],
    subscription: Optional[Subscription],
    db: AsyncSession,
) -> Dict[str, Any]:
    """Role/verification-aware capability flags so the frontend can render the
    right buttons (subscribe / cancel / upgrade) without re-deriving the rules.

    ``reason`` explains why ``can_subscribe`` is False (role or missing
    verification) so the UI can prompt the next step.
    """
    # Admin/advisor never subscribe.
    if user.role in (Role.ADMIN, Role.ADVISOR):
        return {
            "subscription_required": False,
            "can_subscribe": False,
            "can_cancel": False,
            "can_upgrade": False,
            "reason": "Your account does not require a subscription.",
        }

    has_active = bool(subscription and subscription.status == SubscriptionStatus.ACTIVE)

    reason: Optional[str] = None
    eligible = True
    if not is_email_verified(user):
        eligible = False
        reason = "Verify your email to purchase a plan."
    elif account is None or not await is_kyc_approved(db, account.id):
        # No account means the user hasn't started KYC yet -> not eligible.
        eligible = False
        reason = "Complete identity verification (Persona) to purchase a plan."

    return {
        "subscription_required": True,
        # Can start a new plan only when eligible and not already active.
        "can_subscribe": eligible and not has_active,
        # Can cancel only an active plan that isn't already pending cancellation.
        "can_cancel": has_active and not bool(getattr(subscription, "cancel_at_period_end", False)),
        # Can upgrade/downgrade only an active plan.
        "can_upgrade": has_active,
        "reason": reason,
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
    # Admin/advisor accounts do not use subscriptions — only investors subscribe.
    if current_user.role in (Role.ADMIN, Role.ADVISOR):
        raise ForbiddenException(
            "Your account does not require a subscription.",
            code="SUBSCRIPTION_NOT_APPLICABLE",
        )

    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    # Only a verified investor may purchase: email verified AND Persona (KYC) approved.
    if not is_email_verified(current_user):
        raise ForbiddenException(
            "Verify your email before purchasing a plan.",
            code="EMAIL_NOT_VERIFIED",
        )
    if not await is_kyc_approved(db, account.id):
        raise ForbiddenException(
            "Complete identity verification (Persona) before purchasing a plan.",
            code="KYC_NOT_APPROVED",
        )

    # Validate plan_id (accepts both bare and legacy 'plan_'-prefixed IDs)
    plan_id = normalize_plan_id(subscription_data.plan_id)
    if plan_id not in PLANS_CONFIG:
        raise BadRequestException("Invalid plan_id provided", code="PLAN_INVALID")

    plan_config = PLANS_CONFIG[plan_id]
    
    # Validate billing_cycle
    if subscription_data.billing_cycle not in ["monthly", "annual"]:
        raise BadRequestException("billing_cycle must be 'monthly' or 'annual'", code="BILLING_CYCLE_INVALID")
    
    # Get price based on billing cycle
    if subscription_data.billing_cycle == "monthly":
        base_amount = plan_config["monthly_price"]
    else:
        base_amount = plan_config["annual_price"]
    
    if base_amount is None:
        raise BadRequestException("This plan requires custom pricing. Please contact support.", code="PLAN_REQUIRES_CUSTOM_PRICING")

    final_amount = base_amount
    
    # Check if subscription already exists
    existing_result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    existing = existing_result.scalar_one_or_none()

    # Backstop guard: never create/overwrite-charge on top of a live subscription —
    # those users belong in the upgrade flow. Re-subscribing on an expired/cancelled
    # record is still allowed (it reactivates below).
    if existing and existing.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE):
        raise ConflictException(
            "You already have an active subscription. Use the upgrade flow to change plans.",
            code="SUBSCRIPTION_ALREADY_EXISTS",
        )

    # Map plan_id to internal enum
    internal_plan = PLAN_ID_TO_ENUM.get(plan_id, SubscriptionPlan.FREE)
    
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
                "plan_id": plan_id,
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
        existing.plan_tier = plan_id
        existing.billing_cycle = subscription_data.billing_cycle
        existing.status = SubscriptionStatus.ACTIVE
        existing.amount = final_amount
        existing.current_period_start = now
        existing.current_period_end = period_end
        existing.cancel_at_period_end = False
        existing.cancelled_at = None
        subscription = existing
    else:
        subscription = Subscription(
            account_id=account.id,
            plan=internal_plan,
            plan_tier=plan_id,
            billing_cycle=subscription_data.billing_cycle,
            status=SubscriptionStatus.ACTIVE,
            amount=final_amount,
            currency="USD",
            current_period_start=now,
            current_period_end=period_end,
            cancel_at_period_end=False,
        )
        db.add(subscription)
    
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
        billing_cycle=subscription_data.billing_cycle,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        canceled_at=subscription.cancelled_at,
        features=plan_config["features"],
        created_at=subscription.created_at
    )

    # A payment intent that has not yet succeeded means the frontend must complete
    # confirmation/3DS via Stripe.js using the client_secret.
    requires_action = bool(
        payment_intent and payment_intent.status not in ("succeeded", "processing")
    )

    logger.info(f"Subscription created: {subscription.id}")
    return SubscriptionCreateResponse(
        subscription=subscription_response,
        payment_intent=payment_intent,
        requires_action=requires_action,
        client_secret=payment_intent.client_secret if payment_intent else None,
    )


@router.get("")
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the current subscription plus role/verification-aware capability flags.

    Response ``data`` shape (always this shape, for every role):
        {
          "subscription": <object|null>,
          "subscription_required": bool,   # false for admin/advisor
          "can_subscribe": bool,
          "can_cancel": bool,
          "can_upgrade": bool,
          "reason": str|null               # why can_subscribe is false
        }
    """
    # Admin/advisor accounts do not require a subscription — return a graceful
    # payload (HTTP 200) instead of risking a 404 from the account lookup.
    if current_user.role in (Role.ADMIN, Role.ADVISOR):
        caps = await build_capabilities(current_user, None, None, db)
        return success_envelope(
            data={"subscription": None, **caps},
            message="Your account does not require a subscription.",
        )

    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    # No account yet (e.g. a brand-new investor before KYC, or a user just promoted
    # to investor) — return graceful capability flags instead of a 404.
    if not account:
        caps = await build_capabilities(current_user, None, None, db)
        return success_envelope(
            data={"subscription": None, **caps},
            message="No active subscription found.",
        )

    result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    subscription = result.scalar_one_or_none()

    # No subscription yet: still return capability flags so the UI knows whether
    # the "Subscribe" button should be enabled (and why not, if disabled).
    if not subscription:
        caps = await build_capabilities(current_user, account, None, db)
        return success_envelope(
            data={"subscription": None, **caps},
            message="No active subscription found.",
        )

    # Lazily expire an active subscription whose period has lapsed.
    now = datetime.now(timezone.utc)
    if subscription.status == SubscriptionStatus.ACTIVE and subscription.current_period_end:
        period_end = subscription.current_period_end
        if period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=timezone.utc)
        if period_end < now:
            subscription.status = SubscriptionStatus.EXPIRED
            await db.commit()

    plan_id = get_plan_tier(subscription)
    plan_config = PLANS_CONFIG.get(plan_id, PLANS_CONFIG["starter"])
    billing_cycle = get_billing_cycle(subscription)

    caps = await build_capabilities(current_user, account, subscription, db)
    subscription_payload = SubscriptionResponse(
        id=subscription.id,
        plan_id=plan_id,
        plan_name=plan_config["name"],
        status=subscription.status.value,
        amount=subscription.amount,
        currency=subscription.currency,
        billing_cycle=billing_cycle,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        canceled_at=subscription.cancelled_at,
        features=plan_config["features"],
        created_at=subscription.created_at,
    )
    return success_envelope(
        data={"subscription": subscription_payload, **caps},
        message="Subscription retrieved successfully.",
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
    # Only investors hold subscriptions; admin/advisor have nothing to cancel.
    if current_user.role in (Role.ADMIN, Role.ADVISOR):
        raise ForbiddenException(
            "Your account does not have a subscription to cancel.",
            code="SUBSCRIPTION_NOT_APPLICABLE",
        )

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
        raise BadRequestException("No active subscription to cancel", code="NO_ACTIVE_SUBSCRIPTION")

    if subscription.status != SubscriptionStatus.ACTIVE:
        raise BadRequestException("No active subscription to cancel", code="NO_ACTIVE_SUBSCRIPTION")

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
        subscription.cancel_at_period_end = False
        subscription.cancelled_at = datetime.now(timezone.utc)
        message = "Subscription cancelled immediately"
    else:
        # Stays ACTIVE until the period ends, then expires; flag the pending cancel.
        subscription.cancel_at_period_end = True
        subscription.cancelled_at = datetime.now(timezone.utc)
        period_end_str = subscription.current_period_end.isoformat() if subscription.current_period_end else "end of period"
        message = f"Subscription will remain active until {period_end_str}"

    await db.commit()
    await db.refresh(subscription)

    # Map to response format
    plan_id = get_plan_tier(subscription)
    plan_config = PLANS_CONFIG.get(plan_id, PLANS_CONFIG["starter"])

    subscription_response = {
        "id": str(subscription.id),
        "plan_id": plan_id,
        "plan_name": plan_config["name"],
        "status": subscription.status.value,
        "cancel_at_period_end": subscription.cancel_at_period_end,
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
    # Only investors hold subscriptions.
    if current_user.role in (Role.ADMIN, Role.ADVISOR):
        raise ForbiddenException(
            "Your account does not require a subscription.",
            code="SUBSCRIPTION_NOT_APPLICABLE",
        )

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
        raise NotFoundException("Subscription", str(account.id), code="SUBSCRIPTION_NOT_FOUND")

    if subscription.status == SubscriptionStatus.ACTIVE:
        raise BadRequestException("Subscription is already active", code="SUBSCRIPTION_ALREADY_ACTIVE")

    # Renew on the same tier + cycle the user previously had.
    now = datetime.now(timezone.utc)
    billing_cycle = get_billing_cycle(subscription)
    period_end = now + (timedelta(days=365) if billing_cycle == "annual" else timedelta(days=30))

    # Check if payment is required
    plan_id = get_plan_tier(subscription)
    plan_config = PLANS_CONFIG.get(plan_id, PLANS_CONFIG["starter"])
    
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
    subscription.plan_tier = plan_id
    subscription.billing_cycle = billing_cycle
    subscription.cancel_at_period_end = False
    subscription.cancelled_at = None
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
    # Only investors hold subscriptions.
    if current_user.role in (Role.ADMIN, Role.ADVISOR):
        raise ForbiddenException(
            "Your account does not require a subscription.",
            code="SUBSCRIPTION_NOT_APPLICABLE",
        )

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
        raise NotFoundException("Subscription", str(account.id), code="SUBSCRIPTION_NOT_FOUND")

    if subscription.status != SubscriptionStatus.ACTIVE:
        raise BadRequestException("Subscription must be active to upgrade/downgrade", code="SUBSCRIPTION_NOT_ACTIVE")

    # Get current plan info
    current_plan_id = get_plan_tier(subscription)
    current_plan_config = PLANS_CONFIG.get(current_plan_id, PLANS_CONFIG["starter"])

    # Determine new plan_id (accepts both bare and legacy 'plan_'-prefixed IDs)
    new_plan_id = normalize_plan_id(upgrade_data.plan_id) if upgrade_data.plan_id else current_plan_id
    if new_plan_id not in PLANS_CONFIG:
        raise BadRequestException("Invalid plan_id provided", code="PLAN_INVALID")

    new_plan_config = PLANS_CONFIG[new_plan_id]

    # Determine new billing cycle
    current_billing_cycle = get_billing_cycle(subscription)

    new_billing_cycle = upgrade_data.billing_cycle if upgrade_data.billing_cycle else current_billing_cycle
    if new_billing_cycle not in ["monthly", "annual"]:
        raise BadRequestException("billing_cycle must be 'monthly' or 'annual'", code="BILLING_CYCLE_INVALID")
    
    # Get prices
    if new_billing_cycle == "monthly":
        new_amount = new_plan_config["monthly_price"]
    else:
        new_amount = new_plan_config["annual_price"]
    
    if new_amount is None:
        raise BadRequestException("This plan requires custom pricing. Please contact support.", code="PLAN_REQUIRES_CUSTOM_PRICING")
    
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
                "status": stripe_payment_intent.get("status"),
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
    subscription.plan_tier = new_plan_id
    subscription.billing_cycle = new_billing_cycle
    subscription.amount = new_amount
    subscription.current_period_start = now
    subscription.current_period_end = new_period_end
    # A plan change clears any pending end-of-period cancellation.
    subscription.cancel_at_period_end = False
    subscription.cancelled_at = None

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
        cancel_at_period_end=subscription.cancel_at_period_end,
        canceled_at=subscription.cancelled_at,
        created_at=subscription.created_at
    )
    
    requires_action = bool(
        payment_intent and payment_intent.get("status") not in ("succeeded", "processing")
    )

    logger.info(f"Subscription upgraded/downgraded: {subscription.id}")
    return {
        "subscription": subscription_response,
        "payment_intent": payment_intent,
        "requires_action": requires_action,
        "client_secret": payment_intent.get("client_secret") if payment_intent else None,
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
    
    data = []
    for subscription in subscriptions:
        plan_id = get_plan_tier(subscription)
        plan_config = PLANS_CONFIG.get(plan_id, PLANS_CONFIG["starter"])
        billing_cycle = get_billing_cycle(subscription)

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
@limiter.exempt
async def subscription_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle Stripe subscription webhook events"""
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature") or request.headers.get("stripe-signature")

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
            stripe_status = data.get("status")
            if stripe_status == "active":
                subscription.status = SubscriptionStatus.ACTIVE
            elif stripe_status == "canceled":
                subscription.status = SubscriptionStatus.CANCELLED
            elif stripe_status == "past_due":
                subscription.status = SubscriptionStatus.PAST_DUE

            if data.get("current_period_start"):
                subscription.current_period_start = datetime.fromtimestamp(
                    data["current_period_start"], tz=timezone.utc
                )
            if data.get("current_period_end"):
                subscription.current_period_end = datetime.fromtimestamp(
                    data["current_period_end"], tz=timezone.utc
                )
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
            subscription.cancelled_at = datetime.now(timezone.utc)
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

