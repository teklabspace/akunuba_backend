from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime
from app.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.models.account import Account
from app.models.payment import Subscription, SubscriptionPlan, SubscriptionStatus
from app.core.exceptions import UnauthorizedException, ForbiddenException, NotFoundException
from app.core.features import Feature, get_permissions, get_plan_limits, has_feature
from sqlalchemy import select

security = HTTPBearer()


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
    
    if subscription.current_period_end and subscription.current_period_end < datetime.utcnow():
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
    
    if subscription and subscription.current_period_end and subscription.current_period_end >= datetime.utcnow():
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

