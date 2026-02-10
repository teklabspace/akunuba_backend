from fastapi import APIRouter, Depends, Query, Body, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func, and_, desc, or_
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.asset import Asset, AssetType, AssetValuation, AssetOwnership
from app.models.portfolio import Portfolio
from app.models.banking import LinkedAccount, Transaction, AccountType as BankingAccountType
from app.models.order import Order, OrderStatus, OrderType
from app.models.notification import Notification, NotificationType
from app.core.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger
from app.integrations.polygon_client import PolygonClient
from app.integrations.alpaca_client import AlpacaClient
from app.integrations.plaid_client import PlaidClient
from pydantic import BaseModel, Field

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
    
    # Calculate daily returns (simplified - using daily snapshots for better granularity)
    daily_returns = []
    # Use daily snapshots instead of weekly for better data points
    step = max(1, days // 30)  # Limit to ~30 data points max
    for i in range(days, -1, -step):
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
        
        # Always add the snapshot, even if value is 0
        daily_returns.append({
            "date": snapshot_date.date().isoformat(),  # Use date only, not datetime
            "value": float(snapshot_value)
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
                    "symbol": asset.symbol or asset.name[:10] if asset.name else "N/A",
                    "name": asset.name or "Unknown Asset",
                    "return_percentage": float(asset_return),
                    "value": float(asset.current_value)
                }
            
            if asset_return < min_return:
                min_return = asset_return
                worst_performer = {
                    "symbol": asset.symbol or asset.name[:10] if asset.name else "N/A",
                    "name": asset.name or "Unknown Asset",
                    "return_percentage": float(asset_return),
                    "value": float(asset.current_value)
                }
    
    return PerformanceMetrics(
        total_return=total_return,
        total_return_percentage=total_return_percentage,
        period_days=days,
        current_value=current_value,
        historical_value=historical_value,
        daily_returns=daily_returns if daily_returns else [],
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
    try:
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
                historical_value=Decimal("0.00"),
                daily_returns=[],
                best_performer=None,
                worst_performer=None
            )
        
        return performance_data
    except Exception as e:
        logger.error(f"Error in get_performance endpoint: {e}", exc_info=True)
        # Return empty performance on error instead of 500
        return PerformanceMetrics(
            total_return=Decimal("0.00"),
            total_return_percentage=Decimal("0.00"),
            period_days=days,
            current_value=Decimal("0.00"),
            historical_value=Decimal("0.00"),
            daily_returns=[],
            best_performer=None,
            worst_performer=None
        )


@router.get("/history", response_model=List[Dict[str, Any]])
async def get_portfolio_history(
    days: int = Query(30, ge=1, le=365, description="Number of days of history"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get historical portfolio values.

    This endpoint is hardened to always return JSON (empty list on unexpected errors)
    so that frontend clients never receive HTML error pages.
    """
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
            return []
        
        history = []
        # Use timezone-aware UTC datetimes to avoid naive/aware comparison issues
        now = datetime.now(timezone.utc)
        for i in range(days, 0, -1):
            snapshot_date = now - timedelta(days=i)
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
    except NotFoundException:
        # Preserve 404 semantics for missing account
        raise
    except Exception as e:
        # Log and return an empty array instead of propagating an HTML error page
        logger.error(f"Error in get_portfolio_history: {e}", exc_info=True)
        return []


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


# ============================================================================
# PORTFOLIO OVERVIEW SECTION
# ============================================================================

class PortfolioSummaryResponse(BaseModel):
    total_portfolio_value: Decimal
    total_invested: Decimal
    total_returns: Decimal
    return_percentage: Decimal
    today_change: Decimal
    today_change_percentage: Decimal
    cash_available: Decimal
    cash_percentage: Decimal
    asset_types_count: int
    total_holdings: int


@router.get("/summary", response_model=Dict[str, PortfolioSummaryResponse])
async def get_portfolio_summary(
    time_range: Optional[str] = Query("ALL", description="Time range: 1D, 1W, 1M, 3M, 1Y, ALL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get portfolio summary with key metrics"""
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
    
    # Calculate totals
    total_portfolio_value = sum([asset.current_value for asset in assets]) if assets else Decimal("0.00")
    
    # Calculate total invested (sum of initial values or cost basis)
    total_invested = Decimal("0.00")
    for asset in assets:
        # Try to get first valuation as cost basis
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
            total_invested += asset.current_value  # Fallback
    
    total_returns = total_portfolio_value - total_invested
    return_percentage = (total_returns / total_invested * 100) if total_invested > 0 else Decimal("0.00")
    
    # Calculate today's change (compare with yesterday's value)
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    today_value = total_portfolio_value
    
    yesterday_value = Decimal("0.00")
    for asset in assets:
        yesterday_valuation_result = await db.execute(
            select(AssetValuation)
            .where(
                and_(
                    AssetValuation.asset_id == asset.id,
                    AssetValuation.valuation_date <= datetime.combine(yesterday, datetime.min.time())
                )
            )
            .order_by(desc(AssetValuation.valuation_date))
            .limit(1)
        )
        yesterday_valuation = yesterday_valuation_result.scalar_one_or_none()
        if yesterday_valuation:
            yesterday_value += yesterday_valuation.value
        else:
            yesterday_value += asset.current_value
    
    today_change = today_value - yesterday_value
    today_change_percentage = (today_change / yesterday_value * 100) if yesterday_value > 0 else Decimal("0.00")
    
    # Get cash available (from linked accounts or Alpaca)
    cash_available = Decimal("0.00")
    try:
        alpaca_account = AlpacaClient.get_account()
        if alpaca_account:
            if isinstance(alpaca_account, dict):
                cash_available = Decimal(str(alpaca_account.get("cash", 0)))
            else:
                cash_available = Decimal(str(getattr(alpaca_account, "cash", 0)))
    except:
        pass
    
    # Also check linked accounts
    linked_accounts_result = await db.execute(
        select(LinkedAccount).where(
            and_(
                LinkedAccount.account_id == account.id,
                LinkedAccount.is_active == True
            )
        )
    )
    linked_accounts = linked_accounts_result.scalars().all()
    for linked_account in linked_accounts:
        if linked_account.balance:
            cash_available += linked_account.balance
    
    cash_percentage = (cash_available / total_portfolio_value * 100) if total_portfolio_value > 0 else Decimal("0.00")
    
    # Count asset types
    asset_types = set([asset.asset_type.value for asset in assets])
    asset_types_count = len(asset_types)
    total_holdings = len(assets)
    
    return {
        "data": PortfolioSummaryResponse(
            total_portfolio_value=total_portfolio_value,
            total_invested=total_invested,
            total_returns=total_returns,
            return_percentage=return_percentage,
            today_change=today_change,
            today_change_percentage=today_change_percentage,
            cash_available=cash_available,
            cash_percentage=cash_percentage,
            asset_types_count=asset_types_count,
            total_holdings=total_holdings
        )
    }


@router.get("/holdings/top", response_model=Dict[str, List[Dict[str, Any]]])
async def get_top_holdings(
    limit: int = Query(10, ge=1, le=100, description="Number of holdings to return"),
    sort_by: str = Query("value", description="Sort by: value, change, change_percentage"),
    order: str = Query("desc", description="Order: asc, desc"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get top holdings"""
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
    
    holdings = []
    for asset in assets:
        # Get current price from Polygon if available
        current_price = asset.current_value
        if asset.symbol:
            try:
                polygon_price = PolygonClient.get_current_price(asset.symbol)
                if polygon_price:
                    current_price = Decimal(str(polygon_price))
            except:
                pass
        
        # Calculate change (simplified - compare with first valuation)
        first_valuation_result = await db.execute(
            select(AssetValuation)
            .where(AssetValuation.asset_id == asset.id)
            .order_by(AssetValuation.valuation_date)
            .limit(1)
        )
        first_valuation = first_valuation_result.scalar_one_or_none()
        
        avg_price = first_valuation.value if first_valuation else current_price
        change = current_price - avg_price
        change_percentage = (change / avg_price * 100) if avg_price > 0 else Decimal("0.00")
        
        # Calculate shares/quantity (simplified)
        shares = (asset.current_value / current_price) if current_price > 0 else Decimal("0.00")
        
        holdings.append({
            "symbol": asset.symbol or asset.name[:10],
            "name": asset.name,
            "type": asset.asset_type.value.title(),
            "shares": float(shares),
            "avg_price": float(avg_price),
            "current_price": float(current_price),
            "value": float(asset.current_value),
            "change": float(change),
            "change_percentage": float(change_percentage),
            "currency": asset.currency
        })
    
    # Sort holdings
    reverse_order = order.lower() == "desc"
    if sort_by == "value":
        holdings.sort(key=lambda x: x["value"], reverse=reverse_order)
    elif sort_by == "change":
        holdings.sort(key=lambda x: x["change"], reverse=reverse_order)
    elif sort_by == "change_percentage":
        holdings.sort(key=lambda x: x["change_percentage"], reverse=reverse_order)
    
    return {"data": holdings[:limit]}


@router.get("/activity/recent", response_model=Dict[str, List[Dict[str, Any]]])
async def get_recent_activity(
    limit: int = Query(10, ge=1, le=100, description="Number of activities to return"),
    type: Optional[str] = Query("all", description="Filter by type: buy, sell, dividend, transfer, all"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get recent portfolio activity"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    activities = []
    
    # Get Alpaca transactions
    try:
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        alpaca_transactions = AlpacaClient.get_transactions(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            limit=limit * 2
        )
        
        if alpaca_transactions:
            for tx in alpaca_transactions:
                activity_type = tx.get("activity_type", "").lower()
                if type != "all" and activity_type != type.lower():
                    continue
                
                activities.append({
                    "id": str(tx.get("id", "")),
                    "type": activity_type,
                    "asset": tx.get("symbol", ""),
                    "name": tx.get("symbol", ""),
                    "amount": tx.get("qty", 0),
                    "price": tx.get("price", 0),
                    "total": float(tx.get("qty", 0)) * float(tx.get("price", 0)) if tx.get("qty") and tx.get("price") else tx.get("net_amount", 0),
                    "date": tx.get("date", "").split("T")[0] if tx.get("date") else "",
                    "time": tx.get("date", "").split("T")[1][:8] if tx.get("date") and "T" in tx.get("date", "") else "",
                    "currency": "USD"
                })
    except Exception as e:
        logger.error(f"Failed to get Alpaca transactions: {e}")
    
    # Get orders
    orders_result = await db.execute(
        select(Order)
        .where(Order.account_id == account.id)
        .order_by(desc(Order.created_at))
        .limit(limit)
    )
    orders = orders_result.scalars().all()
    
    for order in orders:
        if type != "all" and order.side.lower() != type.lower():
            continue
        
        activities.append({
            "id": str(order.id),
            "type": order.side.lower(),
            "asset": order.symbol,
            "name": order.symbol,
            "amount": float(order.quantity),
            "price": float(order.price) if order.price else 0,
            "total": float(order.quantity * order.price) if order.price else 0,
            "date": order.created_at.date().isoformat() if order.created_at else "",
            "time": order.created_at.time().isoformat()[:8] if order.created_at else "",
            "currency": "USD"
        })
    
    # Sort by date descending
    activities.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    return {"data": activities[:limit]}


@router.get("/market-summary", response_model=Dict[str, Dict[str, List[Dict[str, Any]]]])
async def get_market_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get market summary with indices and crypto prices"""
    indices = []
    crypto = []
    
    # Get S&P 500 and NASDAQ (using Polygon)
    try:
        sp500_snapshot = PolygonClient.get_snapshot("SPY")
        if sp500_snapshot and sp500_snapshot.get("ticker"):
            ticker_data = sp500_snapshot["ticker"]
            day_data = ticker_data.get("day", {})
            prev_day = ticker_data.get("prevDay", {})
            current_price = day_data.get("c") or prev_day.get("c", 0)
            prev_price = prev_day.get("c", 0)
            change = current_price - prev_price if prev_price else 0
            change_pct = (change / prev_price * 100) if prev_price > 0 else 0
            
            indices.append({
                "name": "S&P 500",
                "value": round(current_price * 10, 2),  # SPY is ~1/10 of S&P 500
                "change": round(change * 10, 2),
                "change_percentage": round(change_pct, 2)
            })
    except Exception as e:
        logger.error(f"Failed to get S&P 500 data: {e}")
    
    try:
        nasdaq_snapshot = PolygonClient.get_snapshot("QQQ")
        if nasdaq_snapshot and nasdaq_snapshot.get("ticker"):
            ticker_data = nasdaq_snapshot["ticker"]
            day_data = ticker_data.get("day", {})
            prev_day = ticker_data.get("prevDay", {})
            current_price = day_data.get("c") or prev_day.get("c", 0)
            prev_price = prev_day.get("c", 0)
            change = current_price - prev_price if prev_price else 0
            change_pct = (change / prev_price * 100) if prev_price > 0 else 0
            
            indices.append({
                "name": "NASDAQ",
                "value": round(current_price * 10, 2),  # QQQ is ~1/10 of NASDAQ
                "change": round(change * 10, 2),
                "change_percentage": round(change_pct, 2)
            })
    except Exception as e:
        logger.error(f"Failed to get NASDAQ data: {e}")
    
    # Get crypto prices (BTC, ETH) - using Polygon
    try:
        btc_price = PolygonClient.get_current_price("BTCUSD")
        if btc_price:
            # Get previous day for change calculation
            yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
            btc_prev = PolygonClient.get_daily_open_close("BTCUSD", yesterday)
            prev_price = btc_prev.get("close") if btc_prev else btc_price
            change = btc_price - prev_price if prev_price else 0
            change_pct = (change / prev_price * 100) if prev_price > 0 else 0
            
            crypto.append({
                "symbol": "BTC",
                "name": "Bitcoin",
                "price": round(btc_price, 2),
                "change": round(change, 2),
                "change_percentage": round(change_pct, 2)
            })
    except Exception as e:
        logger.error(f"Failed to get BTC price: {e}")
    
    try:
        eth_price = PolygonClient.get_current_price("ETHUSD")
        if eth_price:
            yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
            eth_prev = PolygonClient.get_daily_open_close("ETHUSD", yesterday)
            prev_price = eth_prev.get("close") if eth_prev else eth_price
            change = eth_price - prev_price if prev_price else 0
            change_pct = (change / prev_price * 100) if prev_price > 0 else 0
            
            crypto.append({
                "symbol": "ETH",
                "name": "Ethereum",
                "price": round(eth_price, 2),
                "change": round(change, 2),
                "change_percentage": round(change_pct, 2)
            })
    except Exception as e:
        logger.error(f"Failed to get ETH price: {e}")
    
    return {
        "data": {
            "indices": indices,
            "crypto": crypto
        }
    }


@router.get("/alerts", response_model=Dict[str, List[Dict[str, Any]]])
async def get_portfolio_alerts(
    status: str = Query("active", description="Filter by status: active, resolved, all"),
    limit: int = Query(10, ge=1, le=100, description="Number of alerts to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get portfolio alerts"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(Notification).where(Notification.account_id == account.id)
    
    if status == "active":
        query = query.where(Notification.is_read == False)
    elif status == "resolved":
        query = query.where(Notification.is_read == True)
    
    result = await db.execute(query.order_by(desc(Notification.created_at)).limit(limit))
    notifications = result.scalars().all()
    
    alerts = []
    for notif in notifications:
        # Map notification types to alert types
        alert_type = "general"
        severity = "info"
        
        if "dividend" in notif.notification_type.value.lower():
            alert_type = "dividend"
        elif "price" in notif.notification_type.value.lower() or "order" in notif.notification_type.value.lower():
            alert_type = "price_alert"
            severity = "warning"
        
        alerts.append({
            "id": str(notif.id),
            "type": alert_type,
            "title": notif.title,
            "message": notif.message,
            "severity": severity,
            "created_at": notif.created_at.isoformat() if notif.created_at else ""
        })
    
    return {"data": alerts}


# ============================================================================
# CRYPTO PORTFOLIO SECTION
# ============================================================================

@router.get("/crypto/summary", response_model=Dict[str, Dict[str, Any]])
async def get_crypto_portfolio_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get crypto portfolio summary"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get crypto assets only
    assets_result = await db.execute(
        select(Asset).where(
            and_(
                Asset.account_id == account.id,
                Asset.asset_type == AssetType.CRYPTO
            )
        )
    )
    crypto_assets = assets_result.scalars().all()
    
    total_value = sum([asset.current_value for asset in crypto_assets]) if crypto_assets else Decimal("0.00")
    
    # Calculate total return
    total_invested = Decimal("0.00")
    for asset in crypto_assets:
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
    
    total_return = total_value - total_invested
    return_percentage = (total_return / total_invested * 100) if total_invested > 0 else Decimal("0.00")
    
    # Calculate volatility (simplified)
    risk_metrics = await calculate_risk_metrics(account.id, db)
    volatility_score = risk_metrics.get("volatility", 0.0)
    
    if volatility_score < 0.02:
        volatility = "Low"
        risk_grade = "A"
        risk_level = "Low"
    elif volatility_score < 0.05:
        volatility = "Medium"
        risk_grade = "B+"
        risk_level = "Moderate"
    else:
        volatility = "High"
        risk_grade = "C"
        risk_level = "High"
    
    return {
        "data": {
            "total_value": float(total_value),
            "total_return": float(total_return),
            "return_percentage": float(return_percentage),
            "volatility": volatility,
            "volatility_score": volatility_score,
            "risk_grade": risk_grade,
            "risk_level": risk_level,
            "currency": "USD"
        }
    }


@router.get("/crypto/performance", response_model=Dict[str, List[Dict[str, Any]]])
async def get_crypto_performance(
    time_range: str = Query(..., description="Time range: 1h, 6h, 12h, 24h, 7d, 30d, 1y"),
    metric: str = Query(..., description="Metric: value-over-time, return-rate, risk-exposure"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get crypto performance data"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get crypto assets
    assets_result = await db.execute(
        select(Asset).where(
            and_(
                Asset.account_id == account.id,
                Asset.asset_type == AssetType.CRYPTO
            )
        )
    )
    crypto_assets = assets_result.scalars().all()
    
    # Map time range to days
    time_range_map = {
        "1h": 0.04, "6h": 0.25, "12h": 0.5, "24h": 1,
        "7d": 7, "30d": 30, "1y": 365
    }
    days = int(time_range_map.get(time_range, 30))
    
    # Get historical data points
    data_points = []
    for i in range(days, 0, -1):
        snapshot_date = datetime.utcnow() - timedelta(days=i)
        snapshot_value = Decimal("0.00")
        
        for asset in crypto_assets:
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
        
        time_str = snapshot_date.strftime("%H:%M") if time_range in ["1h", "6h", "12h", "24h"] else snapshot_date.strftime("%Y-%m-%d")
        data_points.append({
            "time": time_str,
            "value": float(snapshot_value)
        })
    
    return {"data": data_points}


@router.get("/crypto/breakdown", response_model=Dict[str, List[Dict[str, Any]]])
async def get_crypto_breakdown(
    group_by: str = Query(..., description="Group by: value, return-rate"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get crypto portfolio breakdown"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get crypto assets
    assets_result = await db.execute(
        select(Asset).where(
            and_(
                Asset.account_id == account.id,
                Asset.asset_type == AssetType.CRYPTO
            )
        )
    )
    crypto_assets = assets_result.scalars().all()
    
    total_value = sum([asset.current_value for asset in crypto_assets]) if crypto_assets else Decimal("0.00")
    
    # Group by symbol
    crypto_groups = {}
    for asset in crypto_assets:
        symbol = asset.symbol or "Unknown"
        if symbol not in crypto_groups:
            crypto_groups[symbol] = {
                "value": Decimal("0.00"),
                "assets": []
            }
        crypto_groups[symbol]["value"] += asset.current_value
        crypto_groups[symbol]["assets"].append(asset)
    
    breakdown = []
    crypto_colors = {
        "BTC": "#F7931A",
        "ETH": "#627EEA",
        "USDT": "#26A17B",
        "USDC": "#2775CA",
        "BNB": "#F3BA2F",
        "XRP": "#23292F",
        "ADA": "#0033AD",
        "SOL": "#9945FF"
    }
    
    for symbol, data in crypto_groups.items():
        percentage = (data["value"] / total_value * 100) if total_value > 0 else Decimal("0.00")
        color = crypto_colors.get(symbol, "#00D4AA")
        
        breakdown.append({
            "name": symbol,
            "percentage": float(percentage),
            "value": float(data["value"]),
            "color": color
        })
    
    # Sort by value or return rate
    if group_by == "value":
        breakdown.sort(key=lambda x: x["value"], reverse=True)
    elif group_by == "return-rate":
        # Calculate return rate for each
        for item in breakdown:
            symbol = item["name"]
            symbol_assets = crypto_groups[symbol]["assets"]
            total_return = Decimal("0.00")
            total_invested = Decimal("0.00")
            for asset in symbol_assets:
                first_valuation_result = await db.execute(
                    select(AssetValuation)
                    .where(AssetValuation.asset_id == asset.id)
                    .order_by(AssetValuation.valuation_date)
                    .limit(1)
                )
                first_valuation = first_valuation_result.scalar_one_or_none()
                invested = first_valuation.value if first_valuation else asset.current_value
                total_invested += invested
                total_return += (asset.current_value - invested)
            item["return_rate"] = float((total_return / total_invested * 100) if total_invested > 0 else 0)
        breakdown.sort(key=lambda x: x.get("return_rate", 0), reverse=True)
    
    return {"data": breakdown}


@router.get("/crypto/holdings", response_model=Dict[str, List[Dict[str, Any]]])
async def get_crypto_holdings(
    sort_by: str = Query("value", description="Sort by: value, change_24h, change_7d, portfolio_weight"),
    order: str = Query("desc", description="Order: asc, desc"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get crypto holdings"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get crypto assets
    assets_result = await db.execute(
        select(Asset).where(
            and_(
                Asset.account_id == account.id,
                Asset.asset_type == AssetType.CRYPTO
            )
        )
    )
    crypto_assets = assets_result.scalars().all()
    
    total_value = sum([asset.current_value for asset in crypto_assets]) if crypto_assets else Decimal("0.00")
    
    holdings = []
    crypto_icons = {
        "BTC": "₿",
        "ETH": "Ξ",
        "USDT": "$",
        "USDC": "$",
        "BNB": "BNB",
        "XRP": "XRP",
        "ADA": "ADA",
        "SOL": "SOL"
    }
    crypto_colors = {
        "BTC": "#F7931A",
        "ETH": "#627EEA",
        "USDT": "#26A17B",
        "USDC": "#2775CA",
        "BNB": "#F3BA2F",
        "XRP": "#23292F",
        "ADA": "#0033AD",
        "SOL": "#9945FF"
    }
    
    for asset in crypto_assets:
        symbol = asset.symbol or "Unknown"
        current_price = asset.current_value
        
        # Try to get price from Polygon
        if symbol and symbol != "Unknown":
            try:
                polygon_price = PolygonClient.get_current_price(f"{symbol}USD")
                if polygon_price:
                    current_price = Decimal(str(polygon_price))
            except:
                pass
        
        quantity = (asset.current_value / current_price) if current_price > 0 else Decimal("0.00")
        portfolio_weight = (asset.current_value / total_value * 100) if total_value > 0 else Decimal("0.00")
        
        # Calculate 24h and 7d change (simplified)
        change_24h = Decimal("0.00")
        change_7d = Decimal("0.00")
        
        holdings.append({
            "id": str(asset.id),
            "name": asset.name,
            "symbol": symbol,
            "icon": crypto_icons.get(symbol, "●"),
            "icon_bg": crypto_colors.get(symbol, "#00D4AA"),
            "quantity": float(quantity),
            "current_price": float(current_price),
            "change_24h": float(change_24h),
            "change_7d": float(change_7d),
            "market_value": float(asset.current_value),
            "portfolio_weight": float(portfolio_weight),
            "currency": asset.currency
        })
    
    # Sort
    reverse_order = order.lower() == "desc"
    if sort_by == "value":
        holdings.sort(key=lambda x: x["market_value"], reverse=reverse_order)
    elif sort_by == "change_24h":
        holdings.sort(key=lambda x: x["change_24h"], reverse=reverse_order)
    elif sort_by == "change_7d":
        holdings.sort(key=lambda x: x["change_7d"], reverse=reverse_order)
    elif sort_by == "portfolio_weight":
        holdings.sort(key=lambda x: x["portfolio_weight"], reverse=reverse_order)
    
    return {"data": holdings}


# ============================================================================
# CASH FLOW SECTION
# ============================================================================

class TransferRequest(BaseModel):
    transfer_type: str = Field(..., description="internal or external")
    from_account_id: Optional[str] = Field(None, description="Source account ID")
    to_account_id: Optional[str] = Field(None, description="Destination account ID (for internal)")
    wallet_address: Optional[str] = Field(None, description="Wallet address (for external)")
    amount: Decimal
    transfer_date: str
    frequency: str = Field("one-time", description="one-time, daily, weekly, monthly")
    description: Optional[str] = None


@router.get("/cash-flow/summary", response_model=Dict[str, Dict[str, Any]])
async def get_cash_flow_summary(
    period: str = Query(..., description="Period: last30, thisMonth, custom"),
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get cash flow summary"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Determine date range
    if period == "last30":
        end_date_obj = datetime.utcnow()
        start_date_obj = end_date_obj - timedelta(days=30)
    elif period == "thisMonth":
        now = datetime.utcnow()
        start_date_obj = datetime(now.year, now.month, 1)
        end_date_obj = now
    elif period == "custom":
        if not start_date or not end_date:
            raise BadRequestException("start_date and end_date required for custom period")
        start_date_obj = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        end_date_obj = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    else:
        raise BadRequestException("Invalid period")
    
    # Get transactions from linked accounts
    linked_accounts_result = await db.execute(
        select(LinkedAccount).where(
            and_(
                LinkedAccount.account_id == account.id,
                LinkedAccount.is_active == True
            )
        )
    )
    linked_accounts = linked_accounts_result.scalars().all()
    
    total_inflow = Decimal("0.00")
    total_outflow = Decimal("0.00")
    
    for linked_account in linked_accounts:
        transactions_result = await db.execute(
            select(Transaction).where(
                and_(
                    Transaction.linked_account_id == linked_account.id,
                    Transaction.transaction_date >= start_date_obj,
                    Transaction.transaction_date <= end_date_obj
                )
            )
        )
        transactions = transactions_result.scalars().all()
        
        for tx in transactions:
            if tx.amount > 0:
                total_inflow += tx.amount
            else:
                total_outflow += abs(tx.amount)
    
    net_cash_flow = total_inflow - total_outflow
    net_percentage = (net_cash_flow / total_inflow * 100) if total_inflow > 0 else Decimal("0.00")
    
    # Forecast next 30 days (simplified - average daily flow)
    days_in_period = (end_date_obj - start_date_obj).days
    if days_in_period > 0:
        avg_daily_flow = net_cash_flow / days_in_period
        forecast_next_30_days = avg_daily_flow * 30
    else:
        forecast_next_30_days = Decimal("0.00")
    
    return {
        "data": {
            "total_inflow": float(total_inflow),
            "total_outflow": float(total_outflow),
            "net_cash_flow": float(net_cash_flow),
            "net_percentage": float(net_percentage),
            "forecast_next_30_days": float(forecast_next_30_days),
            "currency": "USD"
        }
    }


@router.get("/cash-flow/trends", response_model=Dict[str, List[Dict[str, Any]]])
async def get_cash_flow_trends(
    period: str = Query(..., description="Period: last30, thisMonth, custom"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    granularity: str = Query("monthly", description="daily, weekly, monthly"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get cash flow trends"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Determine date range (same logic as summary)
    if period == "last30":
        end_date_obj = datetime.utcnow()
        start_date_obj = end_date_obj - timedelta(days=30)
    elif period == "thisMonth":
        now = datetime.utcnow()
        start_date_obj = datetime(now.year, now.month, 1)
        end_date_obj = now
    elif period == "custom":
        if not start_date or not end_date:
            raise BadRequestException("start_date and end_date required")
        start_date_obj = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        end_date_obj = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    else:
        raise BadRequestException("Invalid period")
    
    # Get transactions
    linked_accounts_result = await db.execute(
        select(LinkedAccount).where(
            and_(
                LinkedAccount.account_id == account.id,
                LinkedAccount.is_active == True
            )
        )
    )
    linked_accounts = linked_accounts_result.scalars().all()
    
    # Group transactions by period
    trends = {}
    for linked_account in linked_accounts:
        transactions_result = await db.execute(
            select(Transaction).where(
                and_(
                    Transaction.linked_account_id == linked_account.id,
                    Transaction.transaction_date >= start_date_obj,
                    Transaction.transaction_date <= end_date_obj
                )
            )
        )
        transactions = transactions_result.scalars().all()
        
        for tx in transactions:
            tx_date = tx.transaction_date.date()
            
            if granularity == "monthly":
                period_key = tx_date.strftime("%Y-%m")
            elif granularity == "weekly":
                week_start = tx_date - timedelta(days=tx_date.weekday())
                period_key = week_start.strftime("%Y-%m-%d")
            else:  # daily
                period_key = tx_date.isoformat()
            
            if period_key not in trends:
                trends[period_key] = {"inflow": Decimal("0.00"), "outflow": Decimal("0.00")}
            
            if tx.amount > 0:
                trends[period_key]["inflow"] += tx.amount
            else:
                trends[period_key]["outflow"] += abs(tx.amount)
    
    # Format response
    result = []
    for period_key, data in sorted(trends.items()):
        result.append({
            "period": period_key,
            "inflow": float(data["inflow"]),
            "outflow": float(data["outflow"])
        })
    
    return {"data": result}


@router.get("/cash-flow/transactions", response_model=Dict[str, Any])
async def get_cash_flow_transactions(
    period: str = Query(..., description="Period: last30, thisMonth, custom"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    type: str = Query("all", description="inflow, outflow, all"),
    category: Optional[str] = Query(None),
    min_amount: Optional[Decimal] = Query(None),
    max_amount: Optional[Decimal] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get cash flow transactions"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Determine date range
    if period == "last30":
        end_date_obj = datetime.utcnow()
        start_date_obj = end_date_obj - timedelta(days=30)
    elif period == "thisMonth":
        now = datetime.utcnow()
        start_date_obj = datetime(now.year, now.month, 1)
        end_date_obj = now
    elif period == "custom":
        if not start_date or not end_date:
            raise BadRequestException("start_date and end_date required")
        start_date_obj = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        end_date_obj = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
    else:
        raise BadRequestException("Invalid period")
    
    # Get transactions
    linked_accounts_result = await db.execute(
        select(LinkedAccount).where(
            and_(
                LinkedAccount.account_id == account.id,
                LinkedAccount.is_active == True
            )
        )
    )
    linked_accounts = linked_accounts_result.scalars().all()
    
    all_transactions = []
    for linked_account in linked_accounts:
        query = select(Transaction).where(
            and_(
                Transaction.linked_account_id == linked_account.id,
                Transaction.transaction_date >= start_date_obj,
                Transaction.transaction_date <= end_date_obj
            )
        )
        
        if type == "inflow":
            query = query.where(Transaction.amount > 0)
        elif type == "outflow":
            query = query.where(Transaction.amount < 0)
        
        if category:
            query = query.where(Transaction.category == category)
        
        if min_amount:
            query = query.where(Transaction.amount >= min_amount)
        
        if max_amount:
            query = query.where(Transaction.amount <= max_amount)
        
        result = await db.execute(query.order_by(desc(Transaction.transaction_date)))
        transactions = result.scalars().all()
        
        for tx in transactions:
            all_transactions.append({
                "id": str(tx.id),
                "date": tx.transaction_date.date().isoformat(),
                "category": tx.category or "Uncategorized",
                "amount": float(abs(tx.amount)),
                "type": "inflow" if tx.amount > 0 else "outflow",
                "account": linked_account.account_name,
                "account_id": str(linked_account.id),
                "notes": tx.description,
                "currency": tx.currency
            })
    
    # Sort and paginate
    all_transactions.sort(key=lambda x: x["date"], reverse=True)
    total = len(all_transactions)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated = all_transactions[start_idx:end_idx]
    
    return {
        "data": paginated,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }


@router.get("/cash-flow/accounts", response_model=Dict[str, List[Dict[str, Any]]])
async def get_cash_flow_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get accounts list for cash flow"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get linked accounts
    linked_accounts_result = await db.execute(
        select(LinkedAccount).where(
            and_(
                LinkedAccount.account_id == account.id,
                LinkedAccount.is_active == True
            )
        )
    )
    linked_accounts = linked_accounts_result.scalars().all()
    
    accounts_list = []
    for linked_account in linked_accounts:
        account_type_map = {
            BankingAccountType.BANKING: "checking",
            BankingAccountType.BROKERAGE: "investment",
            BankingAccountType.CRYPTO: "crypto"
        }
        
        accounts_list.append({
            "id": str(linked_account.id),
            "name": linked_account.account_name,
            "type": account_type_map.get(linked_account.account_type, "checking"),
            "masked_number": f"****{linked_account.account_number[-4:]}" if linked_account.account_number and len(linked_account.account_number) >= 4 else "****",
            "balance": float(linked_account.balance) if linked_account.balance else 0.0,
            "currency": linked_account.currency
        })
    
    return {"data": accounts_list}


@router.post("/cash-flow/transfers", response_model=Dict[str, Dict[str, Any]])
async def create_transfer(
    transfer_data: TransferRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a transfer"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Validate transfer type
    if transfer_data.transfer_type == "internal":
        if not transfer_data.from_account_id or not transfer_data.to_account_id:
            raise BadRequestException("from_account_id and to_account_id required for internal transfers")
    elif transfer_data.transfer_type == "external":
        if not transfer_data.wallet_address:
            raise BadRequestException("wallet_address required for external transfers")
    else:
        raise BadRequestException("transfer_type must be 'internal' or 'external'")
    
    # Generate transfer ID and confirmation number
    transfer_id = f"transfer_{UUID().hex[:12]}"
    confirmation_number = f"FT{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    
    # In a real implementation, you would:
    # 1. Validate account balances
    # 2. Create transfer record in database
    # 3. Process the transfer via appropriate service
    # 4. Update account balances
    
    return {
        "data": {
            "id": transfer_id,
            "status": "pending",
            "confirmation_number": confirmation_number,
            "created_at": datetime.utcnow().isoformat()
        }
    }


@router.get("/cash-flow/transfers/{transfer_id}", response_model=Dict[str, Dict[str, Any]])
async def get_transfer_status(
    transfer_id: str = Path(..., description="Transfer ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get transfer status"""
    # In a real implementation, fetch from database
    return {
        "data": {
            "id": transfer_id,
            "status": "completed",
            "confirmation_number": f"FT{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "from_account": "Bank A - Checking (****4932)",
            "to_account": "Wallet - Investment",
            "amount": 5000.00,
            "transfer_date": datetime.utcnow().date().isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat()
        }
    }


# ============================================================================
# TRADE ENGINE SECTION
# ============================================================================

@router.get("/trade-engine/search", response_model=Dict[str, List[Dict[str, Any]]])
async def search_assets(
    query: str = Query(..., description="Search query"),
    asset_class: str = Query("all", description="stocks, crypto, bonds, etf, all"),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Search assets for trading"""
    results = []
    
    # Use Polygon API for search
    try:
        tickers = PolygonClient.search_tickers(query, limit=limit)
        if tickers:
            for ticker in tickers:
                ticker_symbol = ticker.get("ticker", "")
                ticker_name = ticker.get("name", "")
                ticker_type = ticker.get("type", "").lower()
                
                # Filter by asset class
                if asset_class != "all":
                    if asset_class == "stocks" and ticker_type not in ["cs", "etp"]:
                        continue
                    elif asset_class == "crypto" and "crypto" not in ticker_type:
                        continue
                    elif asset_class == "bonds" and "bond" not in ticker_type:
                        continue
                    elif asset_class == "etf" and "etp" not in ticker_type:
                        continue
                
                # Get current price
                current_price = PolygonClient.get_current_price(ticker_symbol)
                if not current_price:
                    continue
                
                # Get previous day for change calculation
                yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
                prev_data = PolygonClient.get_daily_open_close(ticker_symbol, yesterday)
                prev_price = prev_data.get("close") if prev_data else current_price
                change = current_price - prev_price if prev_price else 0
                change_pct = (change / prev_price * 100) if prev_price > 0 else 0
                
                asset_type_map = {
                    "cs": "Stock",
                    "etp": "ETF",
                    "crypto": "Crypto",
                    "bond": "Bond"
                }
                
                results.append({
                    "symbol": ticker_symbol,
                    "name": ticker_name,
                    "type": asset_type_map.get(ticker_type, "Stock"),
                    "current_price": round(current_price, 2),
                    "change": round(change, 2),
                    "change_percentage": round(change_pct, 2),
                    "currency": "USD"
                })
    except Exception as e:
        logger.error(f"Failed to search assets: {e}")
    
    return {"data": results[:limit]}


@router.get("/trade-engine/assets/{symbol}", response_model=Dict[str, Dict[str, Any]])
async def get_asset_details(
    symbol: str = Path(..., description="Asset symbol"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get asset details for trading"""
    try:
        # Normalize symbol to uppercase for consistency
        symbol_upper = symbol.upper().strip()
        
        # Get ticker details from Polygon
        ticker_details = PolygonClient.get_ticker_details(symbol_upper)
        snapshot = PolygonClient.get_snapshot(symbol_upper)
        
        # Get current price
        current_price = PolygonClient.get_current_price(symbol_upper)
        
        # If we can't get price, try to get from snapshot
        if not current_price and snapshot:
            ticker_data = snapshot.get("ticker", {})
            day_data = ticker_data.get("day", {})
            prev_day = ticker_data.get("prevDay", {})
            current_price = day_data.get("c") or prev_day.get("c")
            if current_price:
                current_price = float(current_price)
        
        if not current_price:
            raise NotFoundException("Asset", f"Symbol '{symbol}' not found or price unavailable")
        
        # Get previous day for change calculation
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        prev_data = PolygonClient.get_daily_open_close(symbol_upper, yesterday)
        prev_price = prev_data.get("close") if prev_data else current_price
        change = current_price - prev_price if prev_price else 0
        change_pct = (change / prev_price * 100) if prev_price > 0 else 0
        
        # Get additional data from snapshot
        bid = current_price
        ask = current_price
        volume = 0
        market_cap = 0
        exchange = "NASDAQ"
        asset_class = "stock"
        currency = "USD"
        high_52_week = None
        low_52_week = None
        pe_ratio = None
        dividend_yield = None
        
        if snapshot and snapshot.get("ticker"):
            ticker_data = snapshot["ticker"]
            day_data = ticker_data.get("day", {})
            prev_day = ticker_data.get("prevDay", {})
            last_quote = ticker_data.get("lastQuote", {})
            
            if last_quote:
                bid = last_quote.get("bp", current_price)  # bid price
                ask = last_quote.get("ap", current_price)  # ask price
            
            volume = day_data.get("v", 0)
            market_cap = ticker_data.get("market_cap", 0)
            exchange = ticker_data.get("primary_exchange", "NASDAQ")
            
            # Get 52-week high/low if available
            if prev_day:
                high_52_week = prev_day.get("h")
                low_52_week = prev_day.get("l")
        
        # Get asset name from ticker details
        asset_name = symbol_upper
        if ticker_details and ticker_details.get("results"):
            asset_name = ticker_details["results"].get("name", symbol_upper)
        
        # Determine asset class
        if ticker_details and ticker_details.get("results"):
            ticker_type = ticker_details["results"].get("type", "").lower()
            if "crypto" in ticker_type:
                asset_class = "crypto"
            elif "etp" in ticker_type or "etf" in ticker_type:
                asset_class = "etf"
            elif "bond" in ticker_type:
                asset_class = "bond"
            else:
                asset_class = "stock"
        
        return {
            "data": {
                "symbol": symbol_upper,
                "name": asset_name,
                "current_price": round(current_price, 2),
                "previous_close": round(prev_price, 2),
                "change": round(change, 2),
                "change_percentage": round(change_pct, 2),
                "volume": volume,
                "market_cap": market_cap,
                "asset_class": asset_class,
                "exchange": exchange,
                "currency": currency,
                "high_52_week": round(high_52_week, 2) if high_52_week else None,
                "low_52_week": round(low_52_week, 2) if low_52_week else None,
                "pe_ratio": pe_ratio,
                "dividend_yield": dividend_yield
            }
        }
    except NotFoundException:
        raise
    except Exception as e:
        logger.error(f"Error getting asset details for {symbol}: {e}", exc_info=True)
        raise NotFoundException("Asset", f"Symbol '{symbol}' not found or unavailable")


@router.get("/trade-engine/recent-trades", response_model=Dict[str, List[Dict[str, Any]]])
async def get_recent_trades(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get recent trades"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get recent orders
    query = select(Order).where(Order.account_id == account.id)
    if symbol:
        query = query.where(Order.symbol == symbol)
    
    result = await db.execute(query.order_by(desc(Order.created_at)).limit(limit))
    orders = result.scalars().all()
    
    trades = []
    for order in orders:
        # Get current price for change calculation
        current_price = PolygonClient.get_current_price(order.symbol)
        if not current_price:
            current_price = float(order.price) if order.price else 0
        
        prev_price = float(order.price) if order.price else current_price
        change = current_price - prev_price
        change_pct = (change / prev_price * 100) if prev_price > 0 else 0
        
        trades.append({
            "symbol": order.symbol,
            "name": order.symbol,
            "price": round(current_price, 2),
            "change": round(change, 2),
            "change_percentage": round(change_pct, 2),
            "positive": change >= 0
        })
    
    return {"data": trades}


@router.get("/trade-engine/assets/{symbol}/history", response_model=Dict[str, List[Dict[str, Any]]])
async def get_trading_history(
    symbol: str = Path(..., description="Asset symbol"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get trading history for an asset"""
    try:
        # Normalize symbol to uppercase for consistency
        symbol_upper = symbol.upper().strip()
        
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # Get orders for this symbol (case-insensitive match using func.upper)
        orders_result = await db.execute(
            select(Order)
            .where(
                and_(
                    Order.account_id == account.id,
                    sql_func.upper(Order.symbol) == symbol_upper  # Case-insensitive match
                )
            )
            .order_by(desc(Order.created_at))
        )
        orders = orders_result.scalars().all()
        
        history = []
        for order in orders:
            # Map order side to type (buy/sell)
            order_type = order.side.lower() if order.side else "buy"
            
            # Get execution date (use updated_at if filled, otherwise created_at)
            execution_date = order.updated_at if order.status == OrderStatus.FILLED and order.updated_at else order.created_at
            
            history.append({
                "date": order.created_at.date().isoformat() if order.created_at else "",
                "type": order_type,
                "quantity": float(order.quantity),
                "price": float(order.price) if order.price else float(order.filled_price) if order.filled_price else 0,
                "total": float(order.quantity * (order.price if order.price else order.filled_price if order.filled_price else 0)),
                "execution_date": execution_date.isoformat() if execution_date else None
            })
        
        # Return empty array if no history (not 404)
        return {"data": history}
    except NotFoundException:
        raise
    except Exception as e:
        logger.error(f"Error getting trading history for {symbol}: {e}", exc_info=True)
        # Return empty array on error instead of 500
        return {"data": []}


@router.get("/trade-engine/accounts", response_model=Dict[str, List[Dict[str, Any]]])
async def get_brokerage_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get brokerage accounts"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    accounts_list = []
    
    # Get Alpaca account
    try:
        alpaca_account = AlpacaClient.get_account()
        if alpaca_account:
            if isinstance(alpaca_account, dict):
                account_data = alpaca_account
            else:
                account_data = {
                    "account_number": getattr(alpaca_account, "account_number", ""),
                    "buying_power": float(getattr(alpaca_account, "buying_power", 0)),
                    "cash": float(getattr(alpaca_account, "cash", 0)),
                    "portfolio_value": float(getattr(alpaca_account, "portfolio_value", 0))
                }
            
            accounts_list.append({
                "id": f"broker_{account_data.get('account_number', 'default')}",
                "name": "Primary Trading Account",
                "masked_number": f"****{str(account_data.get('account_number', ''))[-4:]}" if account_data.get('account_number') else "****",
                "type": "brokerage",
                "balance": account_data.get("portfolio_value", 0),
                "buying_power": account_data.get("buying_power", 0),
                "currency": "USD"
            })
    except Exception as e:
        logger.error(f"Failed to get Alpaca account: {e}")
    
    return {"data": accounts_list}


class OrderRequest(BaseModel):
    symbol: str
    order_type: str = Field(..., description="buy or sell")
    order_mode: str = Field(..., description="market or limit")
    quantity: Decimal
    limit_price: Optional[Decimal] = Field(None, description="Required for limit orders")
    brokerage_account_id: str
    order_duration: str = Field("day-only", description="day-only, good-till-canceled, immediate-or-cancel")
    open_until: Optional[str] = Field(None, description="For GTC orders")
    notes: Optional[str] = None


@router.post("/trade-engine/orders", response_model=Dict[str, Dict[str, Any]])
async def place_order(
    order_data: OrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Place an order"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Validate limit order
    if order_data.order_mode == "limit" and not order_data.limit_price:
        raise BadRequestException("limit_price required for limit orders")
    
    # Create order via Alpaca
    try:
        if order_data.order_mode == "market":
            alpaca_order = AlpacaClient.create_market_order(
                symbol=order_data.symbol,
                qty=float(order_data.quantity),
                side=order_data.order_type
            )
        else:  # limit
            alpaca_order = AlpacaClient.create_limit_order(
                symbol=order_data.symbol,
                qty=float(order_data.quantity),
                side=order_data.order_type,
                limit_price=float(order_data.limit_price)
            )
        
        if not alpaca_order:
            raise BadRequestException("Failed to create order")
        
        # Save order to database
        order = Order(
            account_id=account.id,
            order_type=OrderType.MARKET if order_data.order_mode == "market" else OrderType.LIMIT,
            symbol=order_data.symbol,
            quantity=order_data.quantity,
            price=order_data.limit_price,
            side=order_data.order_type,
            status=OrderStatus.SUBMITTED,
            alpaca_order_id=str(alpaca_order.get("id", "")) if isinstance(alpaca_order, dict) else str(getattr(alpaca_order, "id", ""))
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        
        order_id = str(alpaca_order.get("id", "")) if isinstance(alpaca_order, dict) else str(getattr(alpaca_order, "id", ""))
        estimated_total = float(order_data.quantity * (order_data.limit_price if order_data.limit_price else 0))
        
        return {
            "data": {
                "order_id": order_id,
                "status": "pending",
                "confirmation_number": f"ORD{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                "estimated_total": estimated_total,
                "created_at": datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Failed to place order: {e}")
        raise BadRequestException(f"Failed to place order: {str(e)}")


@router.get("/trade-engine/orders/{order_id}", response_model=Dict[str, Dict[str, Any]])
async def get_order_status(
    order_id: str = Path(..., description="Order ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get order status"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Try to get from database first
    order_result = await db.execute(
        select(Order).where(
            and_(
                Order.account_id == account.id,
                or_(
                    Order.id == UUID(order_id) if len(order_id) == 36 else False,
                    Order.alpaca_order_id == order_id
                )
            )
        )
    )
    order = order_result.scalar_one_or_none()
    
    if order:
        return {
            "data": {
                "order_id": str(order.alpaca_order_id or order.id),
                "status": order.status.value,
                "symbol": order.symbol,
                "order_type": order.order_type.value,
                "quantity": float(order.quantity),
                "filled_quantity": float(order.filled_quantity) if order.filled_quantity else 0,
                "average_price": float(order.filled_price) if order.filled_price else float(order.price) if order.price else 0,
                "total_value": float(order.quantity * order.price) if order.price else 0,
                "fees": 0.0,  # Would need to calculate from Alpaca
                "created_at": order.created_at.isoformat() if order.created_at else "",
                "filled_at": order.updated_at.isoformat() if order.status == OrderStatus.FILLED and order.updated_at else None
            }
        }
    
    # Try to get from Alpaca
    try:
        alpaca_order = AlpacaClient.get_order_by_id(order_id)
        if alpaca_order:
            if isinstance(alpaca_order, dict):
                order_data = alpaca_order
            else:
                order_data = {
                    "id": getattr(alpaca_order, "id", ""),
                    "status": getattr(alpaca_order, "status", ""),
                    "symbol": getattr(alpaca_order, "symbol", ""),
                    "side": getattr(alpaca_order, "side", ""),
                    "qty": float(getattr(alpaca_order, "qty", 0)),
                    "filled_qty": float(getattr(alpaca_order, "filled_qty", 0)),
                    "filled_avg_price": float(getattr(alpaca_order, "filled_avg_price", 0)),
                    "created_at": getattr(alpaca_order, "created_at", ""),
                    "filled_at": getattr(alpaca_order, "filled_at", "")
                }
            
            return {
                "data": {
                    "order_id": str(order_data.get("id", order_id)),
                    "status": order_data.get("status", "unknown"),
                    "symbol": order_data.get("symbol", ""),
                    "order_type": order_data.get("side", ""),
                    "quantity": order_data.get("qty", 0),
                    "filled_quantity": order_data.get("filled_qty", 0),
                    "average_price": order_data.get("filled_avg_price", 0),
                    "total_value": order_data.get("qty", 0) * order_data.get("filled_avg_price", 0),
                    "fees": 0.0,
                    "created_at": order_data.get("created_at", ""),
                    "filled_at": order_data.get("filled_at")
                }
            }
    except Exception as e:
        logger.error(f"Failed to get order from Alpaca: {e}")
    
    raise NotFoundException("Order", order_id)


@router.delete("/trade-engine/orders/{order_id}", response_model=Dict[str, Dict[str, Any]])
async def cancel_order(
    order_id: str = Path(..., description="Order ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel an order"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Try to cancel via Alpaca
    try:
        success = AlpacaClient.cancel_order(order_id)
        if not success:
            raise BadRequestException("Failed to cancel order")
        
        # Update order in database
        order_result = await db.execute(
            select(Order).where(
                and_(
                    Order.account_id == account.id,
                    Order.alpaca_order_id == order_id
                )
            )
        )
        order = order_result.scalar_one_or_none()
        
        if order:
            order.status = OrderStatus.CANCELLED
            await db.commit()
        
        return {
            "data": {
                "order_id": order_id,
                "status": "cancelled",
                "cancelled_at": datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Failed to cancel order: {e}")
        raise BadRequestException(f"Failed to cancel order: {str(e)}")

