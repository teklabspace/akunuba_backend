from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime, timezone
from app.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.models.account import Account
from app.models.kyc import KYCVerification, KYCStatus
from app.models.payment import Subscription, SubscriptionPlan, SubscriptionStatus
from app.core.permissions import Role
from app.core.exceptions import UnauthorizedException, ForbiddenException, NotFoundException
from app.core.features import Feature, get_permissions, get_plan_limits, has_feature
from sqlalchemy import select

security = HTTPBearer()


def _as_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize a datetime to timezone-aware UTC.

    Values read from ``DateTime(timezone=True)`` columns are timezone-aware, but
    some rows may have been written with a naive ``datetime.utcnow()``. Comparing
    an aware value against a naive ``datetime.utcnow()`` raises
    ``TypeError: can't compare offset-naive and offset-aware datetimes`` and
    surfaces as a 500. Treat naive values as UTC so comparisons are always safe.
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise UnauthorizedException("Invalid authentication credentials")
    
    user_id = payload.get("sub")
    if user_id is None:
        raise UnauthorizedException("Invalid authentication credentials")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if user is None:
        raise UnauthorizedException("User not found")
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    return user


async def get_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Account:
    result = await db.execute(select(Account).where(Account.user_id == current_user.id))
    account = result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    return account


# Statuses that grant product access. ``past_due`` is included so a user whose
# payment retry is in flight can still reach the dashboard/settings to fix billing
# instead of being pushed back to re-subscribe (product decision, see contract doc).
ACCESS_GRANTING_STATUSES = (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)


async def get_active_subscription(
    account: Account = Depends(get_account),
    db: AsyncSession = Depends(get_db)
) -> Optional[Subscription]:
    result = await db.execute(
        select(Subscription).where(
            Subscription.account_id == account.id,
            Subscription.status.in_(ACCESS_GRANTING_STATUSES)
        )
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        return None

    period_end = _as_aware_utc(subscription.current_period_end)
    if period_end and period_end < datetime.now(timezone.utc):
        subscription.status = SubscriptionStatus.EXPIRED
        await db.commit()
        return None

    return subscription


async def get_user_subscription_plan(
    account: Account = Depends(get_account),
    db: AsyncSession = Depends(get_db)
) -> SubscriptionPlan:
    result = await db.execute(
        select(Subscription).where(
            Subscription.account_id == account.id,
            Subscription.status.in_(ACCESS_GRANTING_STATUSES)
        )
    )
    subscription = result.scalar_one_or_none()

    period_end = _as_aware_utc(subscription.current_period_end) if subscription else None
    if subscription and period_end and period_end >= datetime.now(timezone.utc):
        return subscription.plan

    return SubscriptionPlan.FREE


async def require_kyc_verified(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Gate that allows the request only when the caller's identity is verified.

    - Admins are exempt (they never do KYC).
    - Investors and advisors must have a KYC record in ``APPROVED`` status; a
      missing account or non-approved KYC yields a 403 with code ``KYC_REQUIRED``.

    Applied at the router level (see app/main.py) to the dashboard/data APIs so
    KYC is enforced server-side, not just by the frontend. Onboarding routes
    (auth, users, accounts, kyc, kyb, subscriptions, notifications) stay open so
    a user can actually reach verification.
    """
    if current_user.role == Role.ADMIN:
        return current_user

    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    approved = False
    if account:
        kyc_result = await db.execute(
            select(KYCVerification).where(KYCVerification.account_id == account.id)
        )
        kyc = kyc_result.scalar_one_or_none()
        approved = bool(kyc and kyc.status == KYCStatus.APPROVED)

    if not approved:
        raise ForbiddenException(
            "Identity verification (KYC) must be approved to access this resource.",
            code="KYC_REQUIRED",
        )
    return current_user


def require_feature(feature: Feature):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            plan = await get_user_subscription_plan(
                account=kwargs.get('account'),
                db=kwargs.get('db')
            )
            if not has_feature(plan, feature):
                raise ForbiddenException(f"Feature {feature.value} requires a premium subscription")
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def check_usage_limit(limit_type: str, current_count: int, plan: SubscriptionPlan) -> bool:
    from app.core.features import get_limit
    limit = get_limit(plan, limit_type)
    if limit is None:
        return True
    return current_count < limit

