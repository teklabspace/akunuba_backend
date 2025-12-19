from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func, and_, desc
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.asset import Asset, AssetType, AssetValuation, AssetOwnership
from app.models.portfolio import Portfolio
from app.core.exceptions import NotFoundException
from app.utils.logger import logger
from pydantic import BaseModel

router = APIRouter()


class AssetAllocationItem(BaseModel):
    asset_type: str
    count: int
    value: Decimal
    percentage: Decimal
    assets: List[Dict[str, Any]] = []


class PerformanceMetrics(BaseModel):
    total_return: Decimal
    total_return_percentage: Decimal
    period_days: int
    current_value: Decimal
    historical_value: Decimal
    daily_returns: Optional[List[Dict[str, Any]]] = None
    best_performer: Optional[Dict[str, Any]] = None
    worst_performer: Optional[Dict[str, Any]] = None


class PortfolioResponse(BaseModel):
    total_value: Decimal
    currency: str
    asset_count: int
    asset_allocation: List[AssetAllocationItem]
    performance_data: Optional[PerformanceMetrics] = None
    assets: List[Dict[str, Any]]
    last_updated: datetime
    risk_metrics: Optional[Dict[str, Any]] = None


@router.get("", response_model=PortfolioResponse)
async def get_portfolio(
    include_performance: bool = Query(True, description="Include performance metrics"),
    include_risk: bool = Query(True, description="Include risk metrics"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get complete portfolio with aggregations, performance, and risk metrics"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get all assets for the account
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account.id)
    )
    assets = assets_result.scalars().all()
    
    # Calculate total value
    total_value = sum([asset.current_value for asset in assets]) if assets else Decimal("0.00")
    currency = assets[0].currency if assets and len(assets) > 0 else "USD"
    
    # Calculate asset allocation by type
    allocation_by_type = {}
    for asset in assets:
        asset_type = asset.asset_type.value
        if asset_type not in allocation_by_type:
            allocation_by_type[asset_type] = {
                "count": 0,
                "value": Decimal("0.00"),
                "assets": []
            }
        allocation_by_type[asset_type]["count"] += 1
        allocation_by_type[asset_type]["value"] += asset.current_value
        allocation_by_type[asset_type]["assets"].append({
            "id": str(asset.id),
            "name": asset.name,
            "symbol": asset.symbol,
            "value": float(asset.current_value),
            "currency": asset.currency
        })
    
    # Format allocation with percentages
    allocation_items = []
    for asset_type, data in allocation_by_type.items():
        percentage = (data["value"] / total_value * 100) if total_value > 0 else Decimal("0.00")
        allocation_items.append(AssetAllocationItem(
            asset_type=asset_type,
            count=data["count"],
            value=data["value"],
            percentage=percentage,
            assets=data["assets"]
        ))
    
    # Sort by value descending
    allocation_items.sort(key=lambda x: x.value, reverse=True)
    
    # Calculate performance data
    performance_data = None
    if include_performance:
        try:
            performance_data = await calculate_performance(account.id, db, days=30)
        except Exception as e:
            logger.error(f"Failed to calculate performance: {e}")
            performance_data = None
    
    # Calculate risk metrics
    risk_metrics = None
    if include_risk:
        try:
            risk_metrics = await calculate_risk_metrics(account.id, db)
        except Exception as e:
            logger.error(f"Failed to calculate risk metrics: {e}")
            risk_metrics = None
    
    # Update or create portfolio record
    portfolio_result = await db.execute(
        select(Portfolio).where(Portfolio.account_id == account.id)
    )
    portfolio = portfolio_result.scalar_one_or_none()
    
    # Prepare data for storage
    allocation_dict = {
        item.asset_type: {
            "count": item.count,
            "value": float(item.value),
            "percentage": float(item.percentage)
        }
        for item in allocation_items
    }
    
    performance_dict = performance_data.model_dump() if performance_data else None
    
    if portfolio:
        portfolio.total_value = total_value
        portfolio.currency = currency
        portfolio.asset_allocation = allocation_dict
        portfolio.performance_data = performance_dict
        portfolio.last_updated = datetime.utcnow()
    else:
        portfolio = Portfolio(
            account_id=account.id,
            total_value=total_value,
            currency=currency,
            asset_allocation=allocation_dict,
            performance_data=performance_dict,
        )
        db.add(portfolio)
    
    await db.commit()
    await db.refresh(portfolio)
    
    # Format assets for response
    assets_data = [
        {
            "id": str(asset.id),
            "name": asset.name,
            "symbol": asset.symbol,
            "type": asset.asset_type.value,
            "value": float(asset.current_value),
            "currency": asset.currency,
            "description": asset.description,
        }
        for asset in sorted(assets, key=lambda x: x.current_value, reverse=True)
    ]
    
    return PortfolioResponse(
        total_value=total_value,
        currency=currency,
        asset_count=len(assets),
        asset_allocation=allocation_items,
        performance_data=performance_data,
        assets=assets_data,
        last_updated=portfolio.last_updated or datetime.utcnow(),
        risk_metrics=risk_metrics
    )


async def calculate_performance(
    account_id: UUID, 
    db: AsyncSession, 
    days: int = 30
) -> Optional[PerformanceMetrics]:
    """Calculate portfolio performance over time using historical valuations"""
    period_start = datetime.utcnow() - timedelta(days=days)
    
    # Get all assets for the account
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account_id)
    )
    assets = assets_result.scalars().all()
    
    if not assets:
        return None
    
    # Calculate current total value
    current_value = sum([asset.current_value for asset in assets])
    currency = assets[0].currency if assets else "USD"
    
    # Get historical valuations for each asset
    historical_values = {}
    for asset in assets:
        # Get the earliest valuation before or at period start
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
        historical_valuation = valuation_result.scalar_one_or_none()
        
        if historical_valuation:
            historical_values[asset.id] = historical_valuation.value
        else:
            # If no historical valuation, use initial value or current value
            # Try to get the first valuation
            first_valuation_result = await db.execute(
                select(AssetValuation)
                .where(AssetValuation.asset_id == asset.id)
                .order_by(AssetValuation.valuation_date)
                .limit(1)
            )
            first_valuation = first_valuation_result.scalar_one_or_none()
            historical_values[asset.id] = first_valuation.value if first_valuation else asset.current_value
    
    # Calculate historical total value
    historical_value = sum(historical_values.values())
    
    # Calculate returns
    total_return = current_value - historical_value
    total_return_percentage = (
        (total_return / historical_value * 100) if historical_value > 0 else Decimal("0.00")
    )
    
    # Calculate daily returns (simplified - using weekly snapshots)
    daily_returns = []
    for i in range(days, 0, -7):  # Weekly snapshots
        snapshot_date = datetime.utcnow() - timedelta(days=i)
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
                snapshot_value += historical_values.get(asset.id, asset.current_value)
        
        if snapshot_value > 0:
            daily_return = ((snapshot_value - historical_value) / historical_value * 100) if historical_value > 0 else Decimal("0.00")
            daily_returns.append({
                "date": snapshot_date.isoformat(),
                "value": float(snapshot_value),
                "return_percentage": float(daily_return)
            })
    
    # Find best and worst performers
    best_performer = None
    worst_performer = None
    max_return = Decimal("-999999")
    min_return = Decimal("999999")
    
    for asset in assets:
        historical_asset_value = historical_values.get(asset.id, asset.current_value)
        if historical_asset_value > 0:
            asset_return = ((asset.current_value - historical_asset_value) / historical_asset_value * 100)
            
            if asset_return > max_return:
                max_return = asset_return
                best_performer = {
                    "asset_id": str(asset.id),
                    "name": asset.name,
                    "return_percentage": float(asset_return),
                    "current_value": float(asset.current_value),
                    "historical_value": float(historical_asset_value)
                }
            
            if asset_return < min_return:
                min_return = asset_return
                worst_performer = {
                    "asset_id": str(asset.id),
                    "name": asset.name,
                    "return_percentage": float(asset_return),
                    "current_value": float(asset.current_value),
                    "historical_value": float(historical_asset_value)
                }
    
    return PerformanceMetrics(
        total_return=total_return,
        total_return_percentage=total_return_percentage,
        period_days=days,
        current_value=current_value,
        historical_value=historical_value,
        daily_returns=daily_returns if daily_returns else None,
        best_performer=best_performer,
        worst_performer=worst_performer
    )


async def calculate_risk_metrics(account_id: UUID, db: AsyncSession) -> Dict[str, Any]:
    """Calculate risk metrics for the portfolio"""
    # Get all assets
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account_id)
    )
    assets = assets_result.scalars().all()
    
    if not assets:
        return {}
    
    # Get valuation history for volatility calculation
    all_valuations = []
    for asset in assets:
        valuations_result = await db.execute(
            select(AssetValuation)
            .where(AssetValuation.asset_id == asset.id)
            .order_by(AssetValuation.valuation_date)
            .limit(30)  # Last 30 valuations
        )
        asset_valuations = valuations_result.scalars().all()
        if len(asset_valuations) > 1:
            # Calculate returns
            for i in range(1, len(asset_valuations)):
                prev_value = asset_valuations[i-1].value
                curr_value = asset_valuations[i].value
                if prev_value > 0:
                    return_pct = ((curr_value - prev_value) / prev_value) * 100
                    all_valuations.append(float(return_pct))
    
    # Calculate volatility (standard deviation of returns)
    volatility = Decimal("0.00")
    if len(all_valuations) > 1:
        mean_return = sum(all_valuations) / len(all_valuations)
        variance = sum([(r - mean_return) ** 2 for r in all_valuations]) / len(all_valuations)
        volatility = Decimal(str(variance ** 0.5))
    
    # Calculate concentration risk (largest asset percentage)
    total_value = sum([asset.current_value for asset in assets])
    max_asset_value = max([asset.current_value for asset in assets]) if assets else Decimal("0.00")
    concentration_risk = (max_asset_value / total_value * 100) if total_value > 0 else Decimal("0.00")
    
    # Count asset types for diversification
    asset_types = {}
    for asset in assets:
        asset_type = asset.asset_type.value
        asset_types[asset_type] = asset_types.get(asset_type, 0) + 1
    
    diversification_score = len(asset_types) / len(AssetType) * 100 if assets else 0
    
    return {
        "volatility": float(volatility),
        "concentration_risk": float(concentration_risk),
        "diversification_score": float(diversification_score),
        "asset_type_count": len(asset_types),
        "total_assets": len(assets)
    }


@router.get("/performance", response_model=PerformanceMetrics)
async def get_performance(
    days: int = Query(30, ge=1, le=365, description="Number of days for performance calculation"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed performance metrics for the portfolio"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    performance_data = await calculate_performance(account.id, db, days=days)
    
    if not performance_data:
        # Return empty performance if no assets
        return PerformanceMetrics(
            total_return=Decimal("0.00"),
            total_return_percentage=Decimal("0.00"),
            period_days=days,
            current_value=Decimal("0.00"),
            historical_value=Decimal("0.00")
        )
    
    return performance_data


@router.get("/history", response_model=List[Dict[str, Any]])
async def get_portfolio_history(
    days: int = Query(30, ge=1, le=365, description="Number of days of history"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get historical portfolio values"""
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
        return []
    
    history = []
    for i in range(days, 0, -1):
        snapshot_date = datetime.utcnow() - timedelta(days=i)
        snapshot_value = Decimal("0.00")
        
        for asset in assets:
            # Get closest valuation to snapshot date
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
                # Use current value if no historical data
                snapshot_value += asset.current_value
        
        history.append({
            "date": snapshot_date.isoformat(),
            "value": float(snapshot_value),
            "currency": assets[0].currency if assets else "USD"
        })
    
    return history


@router.get("/allocation", response_model=List[AssetAllocationItem])
async def get_allocation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed asset allocation breakdown"""
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
        return []
    
    # Calculate total value
    total_value = sum([asset.current_value for asset in assets])
    
    # Group by asset type
    allocation_by_type = {}
    for asset in assets:
        asset_type = asset.asset_type.value
        if asset_type not in allocation_by_type:
            allocation_by_type[asset_type] = {
                "count": 0,
                "value": Decimal("0.00"),
                "assets": []
            }
        allocation_by_type[asset_type]["count"] += 1
        allocation_by_type[asset_type]["value"] += asset.current_value
        allocation_by_type[asset_type]["assets"].append({
            "id": str(asset.id),
            "name": asset.name,
            "symbol": asset.symbol,
            "value": float(asset.current_value),
            "currency": asset.currency
        })
    
    # Format allocation with percentages
    allocation_items = []
    for asset_type, data in allocation_by_type.items():
        percentage = (data["value"] / total_value * 100) if total_value > 0 else Decimal("0.00")
        allocation_items.append(AssetAllocationItem(
            asset_type=asset_type,
            count=data["count"],
            value=data["value"],
            percentage=percentage,
            assets=data["assets"]
        ))
    
    # Sort by value descending
    allocation_items.sort(key=lambda x: x.value, reverse=True)
    
    return allocation_items


@router.get("/risk", response_model=Dict[str, Any])
async def get_risk_metrics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get portfolio risk metrics"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    risk_metrics = await calculate_risk_metrics(account.id, db)
    
    return risk_metrics


@router.get("/benchmark", response_model=Dict[str, Any])
async def compare_with_benchmark(
    benchmark_value: Decimal = Query(..., description="Benchmark portfolio value for comparison"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Compare portfolio performance with a benchmark"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get portfolio
    portfolio_result = await db.execute(
        select(Portfolio).where(Portfolio.account_id == account.id)
    )
    portfolio = portfolio_result.scalar_one_or_none()
    
    if not portfolio:
        raise NotFoundException("Portfolio", str(account.id))
    
    portfolio_value = portfolio.total_value
    benchmark_value_decimal = Decimal(str(benchmark_value))
    
    # Calculate difference
    difference = portfolio_value - benchmark_value_decimal
    difference_percentage = (
        (difference / benchmark_value_decimal * 100) if benchmark_value_decimal > 0 else Decimal("0.00")
    )
    
    return {
        "portfolio_value": float(portfolio_value),
        "benchmark_value": float(benchmark_value_decimal),
        "difference": float(difference),
        "difference_percentage": float(difference_percentage),
        "outperforming": difference > 0
    }

