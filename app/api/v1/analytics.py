from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.asset import Asset, AssetType, AssetValuation
from app.models.portfolio import Portfolio
from app.integrations.posthog_client import PosthogClient
from app.core.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger
from pydantic import BaseModel

router = APIRouter()


class TrackEventRequest(BaseModel):
    event: str
    properties: Optional[Dict[str, Any]] = None


class IdentifyUserRequest(BaseModel):
    properties: Dict[str, Any]


@router.post("/identify")
async def identify_user(
    identify_data: IdentifyUserRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Identify user in PostHog analytics"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    properties = {
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role.value,
        "is_verified": current_user.is_verified,
        **identify_data.properties
    }
    
    success = PosthogClient.identify(
        distinct_id=str(current_user.id),
        properties=properties
    )
    
    if success:
        logger.info(f"User identified in PostHog: {current_user.id}")
        return {"message": "User identified successfully"}
    else:
        return {"message": "PostHog not configured or identification failed"}


@router.post("/track")
async def track_event(
    event_data: TrackEventRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Track an event in PostHog analytics"""
    success = PosthogClient.track(
        distinct_id=str(current_user.id),
        event=event_data.event,
        properties=event_data.properties
    )
    
    if success:
        logger.info(f"Event tracked in PostHog: {event_data.event} for user {current_user.id}")
        return {"message": "Event tracked successfully"}
    else:
        return {"message": "PostHog not configured or tracking failed"}


@router.post("/track-batch")
async def track_events_batch(
    events: List[TrackEventRequest],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Track multiple events in a single request"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    results = []
    for event_data in events:
        success = PosthogClient.track(
            distinct_id=str(current_user.id),
            event=event_data.event,
            properties=event_data.properties
        )
        results.append({
            "event": event_data.event,
            "success": success
        })
    
    success_count = sum(1 for r in results if r["success"])
    logger.info(f"Batch tracked {success_count}/{len(events)} events for user {current_user.id}")
    
    return {
        "message": f"Tracked {success_count}/{len(events)} events",
        "results": results
    }


@router.post("/page-view")
async def track_page_view(
    page_name: str,
    page_url: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Track a page view event"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    event_properties = {
        "page_name": page_name,
        "page_url": page_url or "",
        **(properties or {})
    }
    
    success = PosthogClient.track(
        distinct_id=str(current_user.id),
        event="$pageview",
        properties=event_properties
    )
    
    if success:
        logger.info(f"Page view tracked: {page_name} for user {current_user.id}")
        return {"message": "Page view tracked successfully"}
    else:
        return {"message": "PostHog not configured or tracking failed"}


@router.get("/dashboard")
async def get_analytics_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get analytics dashboard data (placeholder - PostHog has its own dashboard)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Check if PostHog is configured
    posthog_configured = PosthogClient.get_client() is not None
    
    # Return dashboard info and links
    return {
        "user_id": str(current_user.id),
        "posthog_configured": posthog_configured,
        "dashboard_url": "https://app.posthog.com" if posthog_configured else None,
        "note": "Use PostHog dashboard for detailed analytics. This endpoint provides basic tracking status.",
        "tracking_enabled": posthog_configured,
        "features": {
            "event_tracking": posthog_configured,
            "user_identification": posthog_configured,
            "batch_tracking": posthog_configured,
            "page_view_tracking": posthog_configured
        }
    }


# ==================== PORTFOLIO ANALYTICS ====================

@router.get("/portfolio", response_model=Dict[str, Any])
async def get_portfolio_analytics(
    time_range: str = Query("1Y", description="Time range: 1M, 3M, 6M, 1Y, ALL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get portfolio analytics"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # Map time range to days
        time_range_map = {
            "1M": 30,
            "3M": 90,
            "6M": 180,
            "1Y": 365,
            "ALL": 365
        }
        days = time_range_map.get(time_range, 365)
        
        # Get all assets
        assets_result = await db.execute(
            select(Asset).where(Asset.account_id == account.id)
        )
        assets = assets_result.scalars().all()
        
        if not assets:
            return {
                "total_value": 0.0,
                "total_invested": 0.0,
                "total_return": 0.0,
                "total_return_percentage": 0.0,
                "asset_count": 0,
                "asset_allocation": {},
                "performance_by_period": {}
            }
        
        # Calculate current value
        current_value = sum([asset.current_value for asset in assets])
        
        # Calculate total invested
        total_invested = Decimal("0.00")
        for asset in assets:
            first_valuation_result = await db.execute(
                select(AssetValuation)
                .where(AssetValuation.asset_id == asset.id)
                .order_by(AssetValuation.valuation_date)
                .limit(1)
            )
            first_valuation = first_valuation_result.scalar_one_or_none()
            if first_valuation:
                total_invested += first_valuation.value
            else:
                total_invested += asset.current_value
        
        total_return = current_value - total_invested
        total_return_percentage = (total_return / total_invested * 100) if total_invested > 0 else Decimal("0.00")
        
        # Asset allocation
        asset_allocation = {}
        for asset in assets:
            asset_type = asset.asset_type.value if asset.asset_type else "other"
            if asset_type not in asset_allocation:
                asset_allocation[asset_type] = 0.0
            asset_allocation[asset_type] += float(asset.current_value)
        
        if current_value > 0:
            asset_allocation = {
                k: (v / float(current_value) * 100) for k, v in asset_allocation.items()
            }
        
        # Performance by period
        performance_by_period = {}
        for period in ["1M", "3M", "6M", "1Y"]:
            period_days = time_range_map.get(period, 30)
            period_start = datetime.now(timezone.utc) - timedelta(days=period_days)
            
            period_historical_value = Decimal("0.00")
            for asset in assets:
                valuation_result = await db.execute(
                    select(AssetValuation)
                    .where(
                        and_(
                            AssetValuation.asset_id == asset.id,
                            AssetValuation.valuation_date <= period_start
                        )
                    )
                    .order_by(desc(AssetValuation.valuation_date))
                    .limit(1)
                )
                valuation = valuation_result.scalar_one_or_none()
                if valuation:
                    period_historical_value += valuation.value
                else:
                    period_historical_value += asset.current_value
            
            if period_historical_value > 0:
                period_return = ((current_value - period_historical_value) / period_historical_value * 100)
                performance_by_period[period] = float(period_return)
        
        return {
            "total_value": float(current_value),
            "total_invested": float(total_invested),
            "total_return": float(total_return),
            "total_return_percentage": float(total_return_percentage),
            "asset_count": len(assets),
            "asset_allocation": asset_allocation,
            "performance_by_period": performance_by_period
        }
    except Exception as e:
        logger.error(f"Error getting portfolio analytics: {e}", exc_info=True)
        raise BadRequestException(f"Failed to get portfolio analytics: {str(e)}")


@router.get("/performance", response_model=Dict[str, Any])
async def get_performance_analytics(
    time_range: str = Query("1Y", description="Time range: 1M, 3M, 6M, 1Y, ALL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get performance analytics"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # Map time range to days
        time_range_map = {
            "1M": 30,
            "3M": 90,
            "6M": 180,
            "1Y": 365,
            "ALL": 365
        }
        days = time_range_map.get(time_range, 365)
        
        # Get all assets
        assets_result = await db.execute(
            select(Asset).where(Asset.account_id == account.id)
        )
        assets = assets_result.scalars().all()
        
        if not assets:
            return {
                "total_return": 0.0,
                "total_return_percentage": 0.0,
                "annualized_return": None,
                "volatility": None,
                "sharpe_ratio": None,
                "max_drawdown": None,
                "daily_returns": []
            }
        
        period_start = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Get historical valuations for volatility calculation
        all_valuations = []
        for asset in assets:
            valuations_result = await db.execute(
                select(AssetValuation)
                .where(
                    and_(
                        AssetValuation.asset_id == asset.id,
                        AssetValuation.valuation_date >= period_start
                    )
                )
                .order_by(AssetValuation.valuation_date)
                .limit(30)
            )
            asset_valuations = valuations_result.scalars().all()
            if len(asset_valuations) > 1:
                for i in range(1, len(asset_valuations)):
                    prev_value = asset_valuations[i-1].value
                    curr_value = asset_valuations[i].value
                    if prev_value > 0:
                        return_pct = ((curr_value - prev_value) / prev_value) * 100
                        all_valuations.append(float(return_pct))
        
        # Calculate volatility
        volatility = None
        if len(all_valuations) > 1:
            mean_return = sum(all_valuations) / len(all_valuations)
            variance = sum([(r - mean_return) ** 2 for r in all_valuations]) / len(all_valuations)
            volatility = variance ** 0.5
        
        # Calculate current and historical values
        current_value = sum([asset.current_value for asset in assets])
        historical_value = Decimal("0.00")
        for asset in assets:
            valuation_result = await db.execute(
                select(AssetValuation)
                .where(
                    and_(
                        AssetValuation.asset_id == asset.id,
                        AssetValuation.valuation_date <= period_start
                    )
                )
                .order_by(desc(AssetValuation.valuation_date))
                .limit(1)
            )
            valuation = valuation_result.scalar_one_or_none()
            if valuation:
                historical_value += valuation.value
            else:
                historical_value += asset.current_value
        
        total_return = current_value - historical_value
        total_return_percentage = (total_return / historical_value * 100) if historical_value > 0 else Decimal("0.00")
        
        # Calculate annualized return
        period_years = days / 365.0
        annualized_return = None
        if period_years > 0 and historical_value > 0:
            annualized_return = float(((current_value / historical_value) ** (1 / period_years) - 1) * 100)
        
        # Daily returns (simplified - last 30 days)
        daily_returns = []
        for i in range(30, 0, -1):
            snapshot_date = datetime.now(timezone.utc) - timedelta(days=i)
            snapshot_value = Decimal("0.00")
            for asset in assets:
                valuation_result = await db.execute(
                    select(AssetValuation)
                    .where(
                        and_(
                            AssetValuation.asset_id == asset.id,
                            AssetValuation.valuation_date <= snapshot_date
                        )
                    )
                    .order_by(desc(AssetValuation.valuation_date))
                    .limit(1)
                )
                valuation = valuation_result.scalar_one_or_none()
                if valuation:
                    snapshot_value += valuation.value
                else:
                    snapshot_value += asset.current_value
            
            if historical_value > 0:
                daily_return = ((snapshot_value - historical_value) / historical_value * 100)
                daily_returns.append({
                    "date": snapshot_date.date().isoformat(),
                    "return": float(daily_return)
                })
        
        return {
            "total_return": float(total_return),
            "total_return_percentage": float(total_return_percentage),
            "annualized_return": annualized_return,
            "volatility": volatility,
            "sharpe_ratio": None,  # Would require risk-free rate
            "max_drawdown": None,  # Would require detailed history
            "daily_returns": daily_returns[-30:] if daily_returns else []
        }
    except Exception as e:
        logger.error(f"Error getting performance analytics: {e}", exc_info=True)
        raise BadRequestException(f"Failed to get performance analytics: {str(e)}")


@router.get("/risk", response_model=Dict[str, Any])
async def get_risk_analytics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get risk analytics"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # Get all assets
        assets_result = await db.execute(
            select(Asset).where(Asset.account_id == account.id)
        )
        assets = assets_result.scalars().all()
        
        if not assets:
            return {
                "volatility": 0.0,
                "concentration_risk": 0.0,
                "diversification_score": 0.0,
                "beta": None,
                "value_at_risk": None,
                "risk_level": "low"
            }
        
        # Get valuation history for volatility calculation
        all_valuations = []
        for asset in assets:
            valuations_result = await db.execute(
                select(AssetValuation)
                .where(AssetValuation.asset_id == asset.id)
                .order_by(AssetValuation.valuation_date)
                .limit(30)
            )
            asset_valuations = valuations_result.scalars().all()
            if len(asset_valuations) > 1:
                for i in range(1, len(asset_valuations)):
                    prev_value = asset_valuations[i-1].value
                    curr_value = asset_valuations[i].value
                    if prev_value > 0:
                        return_pct = ((curr_value - prev_value) / prev_value) * 100
                        all_valuations.append(float(return_pct))
        
        # Calculate volatility
        volatility = 0.0
        if len(all_valuations) > 1:
            mean_return = sum(all_valuations) / len(all_valuations)
            variance = sum([(r - mean_return) ** 2 for r in all_valuations]) / len(all_valuations)
            volatility = variance ** 0.5
        
        # Calculate concentration risk (largest asset percentage)
        total_value = sum([asset.current_value for asset in assets])
        max_asset_value = max([asset.current_value for asset in assets]) if assets else Decimal("0.00")
        concentration_risk = float((max_asset_value / total_value * 100) if total_value > 0 else Decimal("0.00"))
        
        # Count asset types for diversification
        asset_types = set([asset.asset_type.value if asset.asset_type else "other" for asset in assets])
        diversification_score = float((len(asset_types) / len(AssetType) * 100) if assets else 0)
        
        # Determine risk level
        if volatility < 2.0 and concentration_risk < 30 and diversification_score > 50:
            risk_level = "low"
        elif volatility < 5.0 and concentration_risk < 50:
            risk_level = "moderate"
        else:
            risk_level = "high"
        
        return {
            "volatility": volatility,
            "concentration_risk": concentration_risk,
            "diversification_score": diversification_score,
            "beta": None,  # Would require market data
            "value_at_risk": None,  # Would require detailed calculation
            "risk_level": risk_level,
            "asset_type_count": len(asset_types),
            "total_assets": len(assets)
        }
    except Exception as e:
        logger.error(f"Error getting risk analytics: {e}", exc_info=True)
        raise BadRequestException(f"Failed to get risk analytics: {str(e)}")

