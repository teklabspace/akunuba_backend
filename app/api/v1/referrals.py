from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.referral import Referral, ReferralReward, ReferralStatus
from app.core.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger
from app.utils.helpers import generate_reference_id
from pydantic import BaseModel

router = APIRouter()


class ReferralResponse(BaseModel):
    id: UUID
    referral_code: str
    referred_email: Optional[str] = None
    status: str
    reward_amount: Decimal
    reward_currency: str
    reward_paid: bool
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReferralStatsResponse(BaseModel):
    total_referrals: int
    completed_referrals: int
    pending_referrals: int
    total_rewards_earned: Decimal
    total_rewards_paid: Decimal
    pending_rewards: Decimal
    currency: str = "USD"


class ReferralListResponse(BaseModel):
    data: List[ReferralResponse]
    total: int
    page: int
    limit: int


class ReferralCodeResponse(BaseModel):
    referral_code: str
    referral_link: str
    created_at: datetime
    total_uses: int
    total_rewards: Decimal


class ReferralRewardResponse(BaseModel):
    id: UUID
    referral_id: UUID
    amount: Decimal
    currency: str
    reward_type: str
    paid: bool
    paid_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ReferralLeaderboardItem(BaseModel):
    account_id: UUID
    referral_code: str
    total_referrals: int
    completed_referrals: int
    total_rewards: Decimal
    rank: int


@router.get("", response_model=ReferralStatsResponse)
async def get_referral_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get referral statistics for the current user"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get all referrals made by this account
    referrals_result = await db.execute(
        select(Referral).where(Referral.referrer_account_id == account.id)
    )
    referrals = referrals_result.scalars().all()
    
    total_referrals = len(referrals)
    completed_referrals = len([r for r in referrals if r.status == ReferralStatus.COMPLETED])
    pending_referrals = len([r for r in referrals if r.status == ReferralStatus.PENDING])
    
    # Calculate rewards
    total_rewards_earned = sum([r.reward_amount for r in referrals])
    total_rewards_paid = sum([r.reward_amount for r in referrals if r.reward_paid])
    pending_rewards = total_rewards_earned - total_rewards_paid
    
    return ReferralStatsResponse(
        total_referrals=total_referrals,
        completed_referrals=completed_referrals,
        pending_referrals=pending_referrals,
        total_rewards_earned=total_rewards_earned,
        total_rewards_paid=total_rewards_paid,
        pending_rewards=pending_rewards,
        currency="USD"
    )


@router.get("/list", response_model=ReferralListResponse)
async def get_referral_list(
    status_filter: Optional[str] = Query(None, description="Filter by status: pending, completed, cancelled"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of referrals"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(Referral).where(Referral.referrer_account_id == account.id)
    
    if status_filter:
        try:
            status_enum = ReferralStatus(status_filter.lower())
            query = query.where(Referral.status == status_enum)
        except ValueError:
            pass
    
    # Get total count
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar() or 0
    
    # Apply pagination
    offset = (page - 1) * limit
    query = query.order_by(desc(Referral.created_at)).offset(offset).limit(limit)
    
    result = await db.execute(query)
    referrals = result.scalars().all()
    
    return ReferralListResponse(
        data=[ReferralResponse.model_validate(r) for r in referrals],
        total=total,
        page=page,
        limit=limit
    )


@router.get("/code", response_model=ReferralCodeResponse)
async def get_referral_code(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's referral code"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Check if referral code exists
    referral_result = await db.execute(
        select(Referral).where(
            and_(
                Referral.referrer_account_id == account.id,
                Referral.referral_code.isnot(None)
            )
        ).order_by(desc(Referral.created_at)).limit(1)
    )
    existing_referral = referral_result.scalar_one_or_none()
    
    if existing_referral:
        referral_code = existing_referral.referral_code
        created_at = existing_referral.created_at
    else:
        # Generate new referral code
        referral_code = f"REF-{generate_reference_id('REF')}"
        created_at = datetime.utcnow()
    
    # Count total uses
    uses_result = await db.execute(
        select(func.count()).select_from(
            select(Referral).where(Referral.referral_code == referral_code).subquery()
        )
    )
    total_uses = uses_result.scalar() or 0
    
    # Calculate total rewards
    rewards_result = await db.execute(
        select(func.sum(Referral.reward_amount)).where(
            and_(
                Referral.referral_code == referral_code,
                Referral.referrer_account_id == account.id
            )
        )
    )
    total_rewards = rewards_result.scalar() or Decimal("0.00")
    
    # Generate referral link (frontend will construct the full URL)
    referral_link = f"/signup?ref={referral_code}"
    
    return ReferralCodeResponse(
        referral_code=referral_code,
        referral_link=referral_link,
        created_at=created_at,
        total_uses=total_uses,
        total_rewards=total_rewards
    )


@router.post("/generate-code", response_model=ReferralCodeResponse)
async def generate_referral_code(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate a new referral code"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Generate unique referral code
    referral_code = f"REF-{generate_reference_id('REF')}"
    
    # Check if code already exists
    existing_result = await db.execute(
        select(Referral).where(Referral.referral_code == referral_code)
    )
    if existing_result.scalar_one_or_none():
        # Regenerate if exists
        referral_code = f"REF-{generate_reference_id('REF')}"
    
    # Create referral record
    referral = Referral(
        referrer_account_id=account.id,
        referral_code=referral_code,
        status=ReferralStatus.PENDING
    )
    
    db.add(referral)
    await db.commit()
    await db.refresh(referral)
    
    logger.info(f"Referral code generated: {referral_code} for account {account.id}")
    
    referral_link = f"/signup?ref={referral_code}"
    
    return ReferralCodeResponse(
        referral_code=referral_code,
        referral_link=referral_link,
        created_at=referral.created_at,
        total_uses=0,
        total_rewards=Decimal("0.00")
    )


@router.get("/rewards", response_model=List[ReferralRewardResponse])
async def get_referral_rewards(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get referral rewards for the current user"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get rewards from referrals made by this account
    rewards_result = await db.execute(
        select(ReferralReward).join(Referral).where(
            Referral.referrer_account_id == account.id
        ).order_by(desc(ReferralReward.created_at))
    )
    rewards = rewards_result.scalars().all()
    
    return [ReferralRewardResponse.model_validate(r) for r in rewards]


@router.get("/leaderboard", response_model=List[ReferralLeaderboardItem])
async def get_referral_leaderboard(
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get referral leaderboard"""
    # Get top referrers by completed referrals
    leaderboard_query = (
        select(
            Referral.referrer_account_id,
            Referral.referral_code,
            func.count(Referral.id).label("total_referrals"),
            func.sum(
                func.case((Referral.status == ReferralStatus.COMPLETED, 1), else_=0)
            ).label("completed_referrals"),
            func.sum(Referral.reward_amount).label("total_rewards")
        )
        .group_by(Referral.referrer_account_id, Referral.referral_code)
        .order_by(desc("completed_referrals"), desc("total_rewards"))
        .limit(limit)
    )
    
    result = await db.execute(leaderboard_query)
    leaderboard_data = result.all()
    
    leaderboard = []
    for rank, row in enumerate(leaderboard_data, start=1):
        leaderboard.append(ReferralLeaderboardItem(
            account_id=row.referrer_account_id,
            referral_code=row.referral_code or "N/A",
            total_referrals=row.total_referrals or 0,
            completed_referrals=int(row.completed_referrals or 0),
            total_rewards=row.total_rewards or Decimal("0.00"),
            rank=rank
        ))
    
    return leaderboard
