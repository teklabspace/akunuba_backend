from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime, timezone
from app.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.models.account import Account
from app.models.payment import Subscription, SubscriptionPlan, SubscriptionStatus
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


async def get_active_subscription(
    account: Account = Depends(get_account),
    db: AsyncSession = Depends(get_db)
) -> Optional[Subscription]:
    result = await db.execute(
        select(Subscription).where(
            Subscription.account_id == account.id,
            Subscription.status == SubscriptionStatus.ACTIVE
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
            Subscription.status == SubscriptionStatus.ACTIVE
        )
    )
    subscription = result.scalar_one_or_none()
    
    period_end = _as_aware_utc(subscription.current_period_end) if subscription else None
    if subscription and period_end and period_end >= datetime.now(timezone.utc):
        return subscription.plan

    return SubscriptionPlan.FREE


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

