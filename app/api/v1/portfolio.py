from fastapi import APIRouter, Depends, Query, Body, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func, and_, desc, or_
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import secrets
from app.config import settings
from app.database import get_db
from app.api.deps import get_current_user, _as_aware_utc
from app.models.user import User
from app.models.account import Account
from app.models.asset import Asset, AssetType, AssetValuation, AssetOwnership
from app.models.portfolio import Portfolio
from app.models.banking import LinkedAccount, Transaction, AccountType as BankingAccountType
from app.models.order import Order, OrderStatus, OrderType
from app.models.cash import CashEntryType, CashTransaction
from app.models.portfolio_share import PortfolioShare
from app.models.notification import Notification, NotificationType
from app.models.transfer import Transfer
from app.core.exceptions import NotFoundException, BadRequestException, GoneException
from app.services.cash_ledger import (
    apply_delta,
    has_sufficient_funds,
    order_cash_delta,
    order_notional,
    record_cash_movement,
)
from app.services.net_worth import compute_net_worth, core_assets, breakdown_dict
from app.services.valuation_history import load_valuations, value_asof, first_value
from app.services.crypto_metrics import metric_series
from app.services.crypto_window import (
    SUPPORTED_TIME_RANGES,
    resolve_window,
    snapshot_points,
)


def _polygon_quote(symbol: str):
    """(price, day_change, day_change_pct) from the previous-close bar — the
    only price source the free-tier Polygon key can always serve, TTL-cached
    inside PolygonClient. Returns None when no price is available."""
    from app.integrations.polygon_client import PolygonClient as _PC

    price = _PC.get_current_price(symbol)
    if not price:
        return None
    prev_bar = _PC.get_previous_close(symbol)
    prev_results = (prev_bar or {}).get("results") or []
    day_open = prev_results[0].get("o") if prev_results else None
    prev_price = float(day_open) if day_open else price
    change = price - prev_price if prev_price else 0.0
    change_pct = (change / prev_price * 100) if prev_price > 0 else 0.0
    return price, change, change_pct
from app.utils.logger import logger
from app.integrations.polygon_client import PolygonClient
from app.integrations.alpaca_client import AlpacaClient
from app.integrations.plaid_client import PlaidClient
from pydantic import BaseModel, Field

router = APIRouter()

# Ungated companion router. Share links are resolved by people who have no
# account at all, so those routes must not sit behind auth + require_kyc_verified
# like the rest of this module. Registered separately in app/main.py.
public_router = APIRouter()


class AssetAllocationItem(BaseModel):
    asset_type: str
    count: int
    value: Decimal
    percentage: Decimal
    assets: List[Dict[str, Any]] = []


class DailyReturnItem(BaseModel):
    date: str
    value: Decimal
    return_value: Decimal = Field(..., alias="return")
    return_percentage: Decimal

    model_config = {
        "populate_by_name": True,
    }


class PerformanceMetrics(BaseModel):
    period_days: int
    current_value: Decimal
    historical_value: Decimal
    total_return: Decimal
    total_return_percentage: Decimal
    daily_returns: List[DailyReturnItem]


class PortfolioResponse(BaseModel):
    total_value: Decimal  # net worth: core assets - liabilities
    currency: str
    asset_count: int
    net_worth_breakdown: Optional[Dict[str, Any]] = None
    asset_allocation: List[AssetAllocationItem]
    performance_data: Optional[PerformanceMetrics] = None
    assets: List[Dict[str, Any]]
    last_updated: datetime
    risk_metrics: Optional[Dict[str, Any]] = None


def _json_safe(value):
    """Recursively convert Decimals to float so a payload can be stored in a JSONB column."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


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

    # Group-aware totals: the headline value is NET WORTH (core assets minus
    # liabilities); allocation runs over core (owned) assets only so debts and
    # record-keeping groups don't appear as wealth.
    breakdown = compute_net_worth(assets)
    portfolio_assets = core_assets(assets)
    total_value = breakdown.net_worth
    allocation_total = breakdown.total_assets
    currency = portfolio_assets[0].currency if portfolio_assets else "USD"

    # Calculate asset allocation by type
    allocation_by_type = {}
    for asset in portfolio_assets:
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
    
    # Format allocation with percentages (of gross owned assets, so they sum to 100)
    allocation_items = []
    for asset_type, data in allocation_by_type.items():
        percentage = (data["value"] / allocation_total * 100) if allocation_total > 0 else Decimal("0.00")
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
    
    # `performance_data` is a JSONB column, so everything stored in it must be
    # JSON-encodable. Pydantic's plain model_dump() hands back live Decimal objects
    # (PerformanceMetrics and DailyReturnItem are Decimal-typed throughout), and the
    # driver cannot encode a Decimal into JSONB — the commit below blew up with a 500
    # for every account that actually had performance history. Accounts with none took
    # the `else None` branch, which is why an empty portfolio looked fine.
    #
    # Cast to float rather than using model_dump(mode="json"), which would stringify the
    # Decimals: reports.py reads this column straight back into its response, and the
    # branch it falls back to emits numbers. The allocation dict just above already does
    # the same float() cast for the same reason.
    performance_dict = _json_safe(performance_data.model_dump()) if performance_data else None
    
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
        for asset in sorted(portfolio_assets, key=lambda x: x.current_value, reverse=True)
    ]

    return PortfolioResponse(
        total_value=total_value,
        currency=currency,
        asset_count=len(portfolio_assets),
        net_worth_breakdown=breakdown_dict(breakdown),
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
    """Calculate portfolio performance over time using historical valuations.

    Optimized to avoid per-day, per-asset DB queries by bulk-loading valuations
    for all assets in the account and computing snapshots in-memory.
    """
    # Use a consistent "now" for the whole calculation
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=days)
    
    # Get all assets for the account — performance is measured over core
    # (owned) assets only; liabilities and record-keeping groups are excluded.
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account_id)
    )
    assets = core_assets(assets_result.scalars().all())

    if not assets:
        return None

    # Calculate current total value
    current_value = sum([asset.current_value for asset in assets])
    currency = assets[0].currency if assets else "USD"
    
    # Bulk-load all valuations for these assets up to "now"
    asset_ids = [asset.id for asset in assets]
    valuations_result = await db.execute(
        select(AssetValuation)
        .where(
            and_(
                AssetValuation.asset_id.in_(asset_ids),
                AssetValuation.valuation_date <= now,
            )
        )
        .order_by(AssetValuation.asset_id, AssetValuation.valuation_date)
    )
    all_valuations = valuations_result.scalars().all()
    
    # Group valuations by asset_id
    valuations_by_asset: Dict[UUID, List[AssetValuation]] = {}
    for v in all_valuations:
        valuations_by_asset.setdefault(v.asset_id, []).append(v)
    
    # Compute historical value per asset at period_start
    historical_values: Dict[UUID, Decimal] = {}
    for asset in assets:
        vals = valuations_by_asset.get(asset.id, [])
        baseline_value: Optional[Decimal] = None
        
        # Find the latest valuation on or before period_start
        for v in reversed(vals):
            if v.valuation_date <= period_start:
                baseline_value = v.value
                break
        
        if baseline_value is not None:
            historical_values[asset.id] = baseline_value
        else:
            # If no valuation before period_start, fall back to first valuation or current value
            first_val = vals[0].value if vals else asset.current_value
            historical_values[asset.id] = first_val
    
    # Calculate historical total value
    historical_value = sum(historical_values.values())
    
    # Calculate returns
    total_return = current_value - historical_value
    total_return_percentage = (
        (total_return / historical_value * 100) if historical_value > 0 else Decimal("0.00")
    )
    
    # Prepare snapshot dates (bounded to ~30 points)
    # Generate dates from (now - days) to today, ensuring no future dates
    daily_returns: List[Dict[str, Any]] = []
    step = max(1, days // 30)  # Limit to ~30 data points max
    today = now.date()
    
    # Generate snapshot dates: from (now - days) up to today (inclusive)
    snapshot_dates = []
    for i in range(0, days + 1, step):
        snapshot_datetime = (now - timedelta(days=days - i)).replace(tzinfo=timezone.utc)
        snapshot_date_only = snapshot_datetime.date()
        
        # Safety check: never include future dates
        if snapshot_date_only <= today:
            snapshot_dates.append(snapshot_datetime)
    
    # Ensure we always include "today" as the last point
    if snapshot_dates and snapshot_dates[-1].date() < today:
        snapshot_dates.append(now)
    
    snapshot_dates.sort()  # Oldest to newest
    
    # For each snapshot date, compute portfolio value using in-memory valuations
    previous_value = historical_value
    for snapshot_date in snapshot_dates:
        snapshot_value = Decimal("0.00")
        
        for asset in assets:
            vals = valuations_by_asset.get(asset.id, [])
            latest_val: Optional[Decimal] = None
            
            # Find latest valuation on or before snapshot_date
            for v in reversed(vals):
                if v.valuation_date <= snapshot_date:
                    latest_val = v.value
                    break
            
            if latest_val is not None:
                snapshot_value += latest_val
            else:
                snapshot_value += historical_values.get(asset.id, asset.current_value)
        
        # Calculate return from previous day
        day_return = snapshot_value - previous_value
        day_return_percentage = (day_return / previous_value * 100) if previous_value > 0 else Decimal("0.00")
        
        daily_returns.append(DailyReturnItem(
            date=snapshot_date.date().isoformat(),
            value=snapshot_value,
            return_value=day_return,
            return_percentage=day_return_percentage
        ))
        
        previous_value = snapshot_value
    
    return PerformanceMetrics(
        period_days=days,
        current_value=current_value,
        historical_value=historical_value,
        total_return=total_return,
        total_return_percentage=total_return_percentage,
        daily_returns=daily_returns if daily_returns else []
    )


async def calculate_risk_metrics(account_id: UUID, db: AsyncSession) -> Dict[str, Any]:
    """Calculate risk metrics for the portfolio (core/owned assets only)"""
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account_id)
    )
    assets = core_assets(assets_result.scalars().all())
    
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
                period_days=days,
                current_value=Decimal("0.00"),
                historical_value=Decimal("0.00"),
                total_return=Decimal("0.00"),
                total_return_percentage=Decimal("0.00"),
                daily_returns=[]
            )
        
        return performance_data
    except Exception as e:
        logger.error(f"Error in get_performance endpoint: {e}", exc_info=True)
        # Return empty performance on error instead of 500
        return PerformanceMetrics(
            period_days=days,
            current_value=Decimal("0.00"),
            historical_value=Decimal("0.00"),
            total_return=Decimal("0.00"),
            total_return_percentage=Decimal("0.00"),
            daily_returns=[]
        )


class PortfolioHistoryItem(BaseModel):
    date: str
    value: Decimal


class PortfolioHistoryResponse(BaseModel):
    data: List[PortfolioHistoryItem]


@router.get("/history", response_model=PortfolioHistoryResponse)
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
        
        # History tracks core (owned) assets so it matches the headline total.
        assets_result = await db.execute(
            select(Asset).where(Asset.account_id == account.id)
        )
        assets = core_assets(assets_result.scalars().all())

        if not assets:
            return PortfolioHistoryResponse(data=[])
        
        # Use timezone-aware UTC datetimes to avoid naive/aware comparison issues
        now = datetime.now(timezone.utc)

        # Bulk-load all valuations for these assets up to "now"
        asset_ids = [asset.id for asset in assets]
        valuations_result = await db.execute(
            select(AssetValuation)
            .where(
                and_(
                    AssetValuation.asset_id.in_(asset_ids),
                    AssetValuation.valuation_date <= now,
                )
            )
            .order_by(AssetValuation.asset_id, AssetValuation.valuation_date)
        )
        all_valuations = valuations_result.scalars().all()

        # Group valuations by asset_id
        valuations_by_asset: Dict[UUID, List[AssetValuation]] = {}
        for v in all_valuations:
            valuations_by_asset.setdefault(v.asset_id, []).append(v)

        # Prepare snapshot dates; to keep performance bounded, limit to ~60 points max
        # Generate dates from (now - days) to today, ensuring no future dates
        step = max(1, days // 60)
        today = now.date()
        
        snapshot_dates = []
        for i in range(0, days + 1, step):
            snapshot_datetime = (now - timedelta(days=days - i)).replace(tzinfo=timezone.utc)
            snapshot_date_only = snapshot_datetime.date()
            
            # Safety check: never include future dates
            if snapshot_date_only <= today:
                snapshot_dates.append(snapshot_datetime)
        
        # Ensure we always include "today" as the last point
        if snapshot_dates and snapshot_dates[-1].date() < today:
            snapshot_dates.append(now)
        
        snapshot_dates.sort()

        history: List[Dict[str, Any]] = []
        default_currency = assets[0].currency if assets else "USD"

        for snapshot_date in snapshot_dates:
            snapshot_value = Decimal("0.00")

            for asset in assets:
                vals = valuations_by_asset.get(asset.id, [])
                latest_val: Optional[Decimal] = None

                # Find latest valuation on or before snapshot_date
                for v in reversed(vals):
                    if v.valuation_date <= snapshot_date:
                        latest_val = v.value
                        break

                if latest_val is not None:
                    snapshot_value += latest_val
                else:
                    # Use current value if no historical data
                    snapshot_value += asset.current_value

            history.append(
                PortfolioHistoryItem(
                    date=snapshot_date.date().isoformat(),
                    value=snapshot_value
                )
            )

        return PortfolioHistoryResponse(data=history)
    except NotFoundException:
        # Preserve 404 semantics for missing account
        raise
    except Exception as e:
        # Log and return an empty array instead of propagating an HTML error page
        logger.error(f"Error in get_portfolio_history: {e}", exc_info=True)
        return PortfolioHistoryResponse(data=[])


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
    
    # Allocation covers core (owned) assets only — liabilities and
    # record-keeping groups aren't part of the wealth being allocated.
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account.id)
    )
    assets = core_assets(assets_result.scalars().all())

    # Live positions at the linked brokerage (Alpaca) join the allocation.
    alpaca_positions = _get_alpaca_positions()

    if not assets and not alpaca_positions:
        return []

    # Calculate total value (manual core assets + brokerage positions)
    total_value = sum([asset.current_value for asset in assets], Decimal("0.00"))
    total_value += Decimal(str(sum(p["market_value"] for p in alpaca_positions)))

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

    for pos in alpaca_positions:
        asset_type = "crypto" if pos["asset_class"] == "crypto" else "stock"
        if asset_type not in allocation_by_type:
            allocation_by_type[asset_type] = {
                "count": 0,
                "value": Decimal("0.00"),
                "assets": []
            }
        allocation_by_type[asset_type]["count"] += 1
        allocation_by_type[asset_type]["value"] += Decimal(str(pos["market_value"]))
        allocation_by_type[asset_type]["assets"].append({
            "id": f"alpaca_{pos['symbol']}",
            "name": f"{pos['symbol']} (Brokerage)",
            "symbol": pos["symbol"],
            "value": pos["market_value"],
            "currency": "USD"
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
    total_portfolio_value: Decimal  # net: assets + cash - debts
    total_assets: Decimal           # gross owned wealth (matches /allocation total)
    total_debts: Decimal
    cash_available: Decimal         # Plaid-synced bank balances
    trading_cash_balance: Decimal   # settled trading cash (accounts.cash_balance)
    total_invested: Decimal         # cost basis (first valuations)
    total_returns: Decimal
    return_percentage: Decimal
    today_change: Decimal
    today_change_percentage: Decimal
    asset_types_count: int
    total_holdings: int
    net_worth_breakdown: Optional[Dict[str, Any]] = None


@router.get("/summary")
async def get_portfolio_summary(
    time_range: Optional[str] = Query("ALL", description="Time range: 1D, 1W, 1M, 3M, 1Y, ALL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get high-level portfolio overview"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get all assets; returns/change math runs over core (owned) assets only,
    # while liabilities feed total_debts below.
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account.id)
    )
    all_assets = assets_result.scalars().all()
    breakdown = compute_net_worth(all_assets)
    assets = core_assets(all_assets)

    total_assets = breakdown.total_assets
    
    # Calculate total invested (sum of initial values or cost basis).
    # Single batched history load — the old per-asset queries were an N+1
    # that pushed this endpoint towards 40s on 90-asset accounts.
    valuations_by_asset = await load_valuations(db, [asset.id for asset in assets])
    total_invested = Decimal("0.00")
    for asset in assets:
        total_invested += first_value(valuations_by_asset.get(asset.id, []), asset)
    
    total_returns = total_assets - total_invested
    return_percentage = (total_returns / total_invested * 100) if total_invested > 0 else Decimal("0.00")
    
    # Calculate today's change (compare with yesterday's value)
    now = datetime.now(timezone.utc)
    today = now.date()
    yesterday = today - timedelta(days=1)
    today_value = total_assets
    
    yesterday_cutoff = datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=timezone.utc)
    yesterday_value = Decimal("0.00")
    for asset in assets:
        asset_history = valuations_by_asset.get(asset.id, [])
        if asset_history:
            yesterday_value += value_asof(asset_history, asset, yesterday_cutoff)
        else:
            yesterday_value += asset.current_value
    
    today_change = today_value - yesterday_value
    today_change_percentage = (today_change / yesterday_value * 100) if yesterday_value > 0 else Decimal("0.00")
    
    # Get cash available (from linked DEPOSITORY accounts only — a linked
    # brokerage/credit/loan account's balance is not cash, and a liability
    # balance is money owed, not money available; counting either here would
    # inflate total_portfolio_value below by exactly the wrong amount).
    cash_available = Decimal("0.00")
    linked_accounts_result = await db.execute(
        select(LinkedAccount).where(
            and_(
                LinkedAccount.account_id == account.id,
                LinkedAccount.is_active == True,
                LinkedAccount.plaid_type == "depository",
            )
        )
    )
    linked_accounts = linked_accounts_result.scalars().all()
    for linked_account in linked_accounts:
        if linked_account.balance:
            cash_available += linked_account.balance
    
    # Settled trading cash is separate money from the Plaid bank balances above
    # — a deposit moves value between the two, it does not create any.
    trading_cash_balance = apply_delta(account.cash_balance, 0)

    # Debts = the Liabilities category group (amount owed stored as positive value)
    total_debts = breakdown.total_liabilities

    # Total portfolio value = assets + bank cash + trading cash - debts
    total_portfolio_value = total_assets + cash_available + trading_cash_balance - total_debts

    return PortfolioSummaryResponse(
        total_portfolio_value=total_portfolio_value,
        total_assets=total_assets,
        total_debts=total_debts,
        cash_available=cash_available,
        trading_cash_balance=trading_cash_balance,
        total_invested=total_invested,
        total_returns=total_returns,
        return_percentage=return_percentage,
        today_change=today_change,
        today_change_percentage=today_change_percentage,
        asset_types_count=len({asset.asset_type for asset in assets if asset.asset_type}),
        total_holdings=len(assets),
        net_worth_breakdown=breakdown_dict(breakdown)
    )


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
    
    # Top holdings = core (owned) assets only; a mortgage is not a holding.
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account.id)
    )
    assets = core_assets(assets_result.scalars().all())

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
    
    # Live positions at the linked brokerage (Alpaca) are holdings too.
    for pos in _get_alpaca_positions():
        qty = pos["qty"]
        avg_price = (pos["cost_basis"] / qty) if qty else pos["current_price"]
        holdings.append({
            "symbol": pos["symbol"],
            "name": f"{pos['symbol']} (Brokerage)",
            "type": "Crypto" if pos["asset_class"] == "crypto" else "Stock",
            "shares": qty,
            "avg_price": avg_price,
            "current_price": pos["current_price"],
            "value": pos["market_value"],
            "change": pos["market_value"] - pos["cost_basis"],
            "change_percentage": pos["unrealized_plpc"] * 100,
            "currency": "USD"
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

    # Quote via previous-close bars (free-tier friendly, TTL-cached in
    # PolygonClient) instead of the snapshot endpoint that 403/429'd and left
    # these cards permanently empty (QA B9).
    try:
        quote = _polygon_quote("SPY")
        if quote:
            price, change, change_pct = quote
            indices.append({
                "name": "S&P 500",
                "value": round(price * 10, 2),  # SPY is ~1/10 of S&P 500
                "change": round(change * 10, 2),
                "change_percentage": round(change_pct, 2)
            })
    except Exception as e:
        logger.error(f"Failed to get S&P 500 data: {e}")

    try:
        quote = _polygon_quote("QQQ")
        if quote:
            price, change, change_pct = quote
            indices.append({
                "name": "NASDAQ",
                "value": round(price * 10, 2),  # QQQ is ~1/10 of NASDAQ
                "change": round(change * 10, 2),
                "change_percentage": round(change_pct, 2)
            })
    except Exception as e:
        logger.error(f"Failed to get NASDAQ data: {e}")

    try:
        quote = _polygon_quote("X:BTCUSD")
        if quote:
            price, change, change_pct = quote
            crypto.append({
                "symbol": "BTC",
                "name": "Bitcoin",
                "price": round(price, 2),
                "change": round(change, 2),
                "change_percentage": round(change_pct, 2)
            })
    except Exception as e:
        logger.error(f"Failed to get BTC price: {e}")

    try:
        eth_quote = _polygon_quote("X:ETHUSD")
        if eth_quote:
            eth_price, change, change_pct = eth_quote

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

def _get_alpaca_positions(asset_class: Optional[str] = None) -> List[Dict[str, Any]]:
    """Live positions from the linked Alpaca brokerage, normalized to floats.

    asset_class: 'crypto' or 'us_equity' to filter, None for all.
    Returns [] when no brokerage is linked or the call fails — portfolio
    endpoints degrade to manual assets only.
    """
    try:
        raw = AlpacaClient.get_positions() or []
    except Exception:
        return []

    def _field(pos, key, default=None):
        if isinstance(pos, dict):
            return pos.get(key, default)
        return getattr(pos, key, default)

    positions = []
    for pos in raw:
        # alpaca-py returns an AssetClass enum ("crypto"/"us_equity" behind
        # .value); the legacy SDK returns the plain string.
        cls_raw = _field(pos, "asset_class", "")
        cls = str(getattr(cls_raw, "value", cls_raw) or "").lower()
        if asset_class and cls != asset_class:
            continue
        try:
            positions.append({
                "symbol": str(_field(pos, "symbol", "") or ""),
                "qty": float(_field(pos, "qty", 0) or 0),
                "market_value": float(_field(pos, "market_value", 0) or 0),
                "current_price": float(_field(pos, "current_price", 0) or 0),
                "cost_basis": float(_field(pos, "cost_basis", 0) or 0),
                "unrealized_plpc": float(_field(pos, "unrealized_plpc", 0) or 0),
                "change_today": float(_field(pos, "change_today", 0) or 0),
                "asset_class": cls,
            })
        except (TypeError, ValueError):
            continue
    return positions


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
    
    # Crypto held at the linked brokerage (Alpaca) is part of the portfolio.
    alpaca_crypto = _get_alpaca_positions("crypto")
    total_value += Decimal(str(sum(p["market_value"] for p in alpaca_crypto)))
    total_invested += Decimal(str(sum(p["cost_basis"] for p in alpaca_crypto)))

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
    time_range: Optional[str] = Query(
        None, description=f"Time range: {', '.join(SUPPORTED_TIME_RANGES)}. Omit when supplying start_date/end_date."
    ),
    metric: str = Query(..., description="Metric: value-over-time, return-rate, risk-exposure"),
    start_date: Optional[datetime] = Query(
        None, description="Custom range start (ISO 8601). Must be paired with end_date; overrides time_range."
    ),
    end_date: Optional[datetime] = Query(
        None, description="Custom range end (ISO 8601). Must be paired with start_date."
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get crypto performance data over a fixed period or a custom date range."""
    # An unrecognised time_range used to fall through to 30 days with a 200,
    # which made the period dropdown look inert. It is now an explicit 400.
    try:
        window = resolve_window(
            time_range=time_range, start_date=start_date, end_date=end_date
        )
    except ValueError as exc:
        raise BadRequestException(str(exc), code="INVALID_TIME_RANGE")

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
    
    # Prefetch valuations once — the old per-point-per-asset queries hammered
    # the remote DB, and int(0.04) days meant intraday ranges produced ZERO
    # points (24h produced exactly one — the "just 1 dot" chart).
    valuations_by_asset: Dict[Any, List[Any]] = {}
    if crypto_assets:
        valuations_result = await db.execute(
            select(AssetValuation)
            .where(AssetValuation.asset_id.in_([a.id for a in crypto_assets]))
            .order_by(AssetValuation.valuation_date)
        )
        for valuation in valuations_result.scalars().all():
            valuations_by_asset.setdefault(valuation.asset_id, []).append(valuation)

    # Brokerage-held crypto has no local history — contributes its live value.
    alpaca_value = Decimal(str(sum(
        p["market_value"] for p in _get_alpaca_positions("crypto")
    )))

    def value_at(snapshot_date: datetime) -> Decimal:
        total = Decimal("0.00")
        for asset in crypto_assets:
            chosen = None
            for valuation in valuations_by_asset.get(asset.id, []):
                # DB dates are tz-aware, snapshots are naive UTC — strip tz
                # before comparing (mixing raises TypeError).
                v_date = valuation.valuation_date
                if v_date.tzinfo is not None:
                    v_date = v_date.replace(tzinfo=None)
                if v_date <= snapshot_date:
                    chosen = valuation
                else:
                    break
            total += chosen.value if chosen else asset.current_value
        return total + alpaca_value

    # One sampling rule for both the dropdown options and a custom range —
    # see app/services/crypto_window.py.
    data_points = []
    snapshot_dates = []
    for moment, label in snapshot_points(window):
        # value_at compares against naive DB dates, so drop tzinfo here.
        snapshot_date = moment.replace(tzinfo=None)
        snapshot_dates.append(snapshot_date)
        data_points.append({
            "time": label,
            "value": float(value_at(snapshot_date)),
        })

    # Each metric tab gets its own series (QA B7: all three used to return the
    # same dollar curve, so the frontend put a % axis on dollar values).
    exposure_denoms = None
    if metric == "risk-exposure":
        all_assets_result = await db.execute(
            select(Asset).where(Asset.account_id == account.id)
        )
        portfolio_assets = core_assets(all_assets_result.scalars().all())
        portfolio_history = await load_valuations(db, [a.id for a in portfolio_assets])
        total_alpaca_value = Decimal(str(sum(
            p["market_value"] for p in _get_alpaca_positions()
        )))
        exposure_denoms = []
        for snapshot_date in snapshot_dates:
            total = sum(
                (value_asof(portfolio_history.get(a.id, []), a, snapshot_date)
                 for a in portfolio_assets),
                Decimal("0.00"),
            )
            exposure_denoms.append(total + total_alpaca_value)

    return {"data": metric_series(data_points, metric, exposure_denoms)}


@router.get("/crypto/breakdown", response_model=Dict[str, List[Dict[str, Any]]])
async def get_crypto_breakdown(
    group_by: str = Query(..., description="Group by: value, return-rate (also accepts return_rate/returnRate)"),
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

    # Brokerage-held crypto (Alpaca) joins the breakdown by symbol.
    for pos in _get_alpaca_positions("crypto"):
        symbol = pos["symbol"].replace("/USD", "").replace("USD", "") or pos["symbol"]
        group = crypto_groups.setdefault(symbol, {"value": Decimal("0.00"), "assets": []})
        group["value"] += Decimal(str(pos["market_value"]))

    total_value = sum(g["value"] for g in crypto_groups.values()) if crypto_groups else Decimal("0.00")

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
    
    # Sort by value or return rate. snake_case and camelCase spellings are
    # accepted for compat — the rest of the API is snake_case (QA B10).
    if group_by in ("return_rate", "returnRate"):
        group_by = "return-rate"
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

    # Brokerage-held crypto (Alpaca) counts toward the total and gets rows.
    alpaca_crypto = _get_alpaca_positions("crypto")
    alpaca_total = Decimal(str(sum(p["market_value"] for p in alpaca_crypto)))

    total_value = (sum([asset.current_value for asset in crypto_assets]) if crypto_assets else Decimal("0.00")) + alpaca_total

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
    
    for pos in alpaca_crypto:
        plain_symbol = pos["symbol"].replace("/USD", "").replace("USD", "") or pos["symbol"]
        weight = (Decimal(str(pos["market_value"])) / total_value * 100) if total_value > 0 else Decimal("0.00")
        holdings.append({
            "id": f"alpaca_{pos['symbol']}",
            "name": f"{plain_symbol} (Brokerage)",
            "symbol": plain_symbol,
            "icon": crypto_icons.get(plain_symbol, "●"),
            "icon_bg": crypto_colors.get(plain_symbol, "#00D4AA"),
            "quantity": pos["qty"],
            "current_price": pos["current_price"],
            "change_24h": pos["change_today"] * 100,
            "change_7d": 0.0,
            "market_value": pos["market_value"],
            "portfolio_weight": float(weight),
            "currency": "USD"
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


class CryptoShareRequest(BaseModel):
    expires_in_days: Optional[int] = Field(
        30, ge=1, le=365, description="Link lifetime in days. Null for a link that never expires."
    )
    email: Optional[str] = Field(None, description="Recipient, recorded for reference only")
    time_range: Optional[str] = Field(
        None, description=f"Snapshot the link opens at: {', '.join(SUPPORTED_TIME_RANGES)}"
    )
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


async def _crypto_snapshot(db: AsyncSession, account: Account, window) -> Dict[str, Any]:
    """The crypto portfolio figures a share link resolves to.

    Deliberately a read-only aggregate — totals, per-symbol allocation and the
    value series — with no asset ids, documents or account identifiers, since
    the audience is whoever holds the link.
    """
    assets_result = await db.execute(
        select(Asset).where(
            and_(
                Asset.account_id == account.id,
                Asset.asset_type == AssetType.CRYPTO,
            )
        )
    )
    crypto_assets = assets_result.scalars().all()

    valuations = await load_valuations(db, [asset.id for asset in crypto_assets])

    alpaca_crypto = _get_alpaca_positions("crypto")
    alpaca_value = Decimal(str(sum(p["market_value"] for p in alpaca_crypto)))
    alpaca_cost = Decimal(str(sum(p["cost_basis"] for p in alpaca_crypto)))

    total_value = sum(
        (asset.current_value for asset in crypto_assets), Decimal("0.00")
    ) + alpaca_value
    total_invested = sum(
        (first_value(valuations.get(asset.id, []), asset) for asset in crypto_assets),
        Decimal("0.00"),
    ) + alpaca_cost

    total_return = total_value - total_invested
    return_percentage = (
        (total_return / total_invested * 100) if total_invested > 0 else Decimal("0.00")
    )

    # Per-symbol allocation, local assets and brokerage positions combined.
    by_symbol: Dict[str, Decimal] = {}
    for asset in crypto_assets:
        symbol = (asset.symbol or "Unknown").upper()
        by_symbol[symbol] = by_symbol.get(symbol, Decimal("0.00")) + asset.current_value
    for position in alpaca_crypto:
        symbol = str(position.get("symbol", "Unknown")).upper()
        by_symbol[symbol] = by_symbol.get(symbol, Decimal("0.00")) + Decimal(
            str(position["market_value"])
        )

    holdings = sorted(
        (
            {
                "symbol": symbol,
                "value": float(value),
                "percentage": float(value / total_value * 100) if total_value > 0 else 0.0,
            }
            for symbol, value in by_symbol.items()
        ),
        key=lambda row: row["value"],
        reverse=True,
    )

    series = []
    for moment, label in snapshot_points(window):
        snapshot_date = moment.replace(tzinfo=None)
        value = sum(
            (
                value_asof(valuations.get(asset.id, []), asset, snapshot_date)
                for asset in crypto_assets
            ),
            Decimal("0.00"),
        )
        series.append({"time": label, "value": float(value + alpaca_value)})

    return {
        "total_value": float(total_value),
        "total_return": float(total_return),
        "return_percentage": float(return_percentage),
        "holdings": holdings,
        "performance": series,
        "currency": "USD",
    }


@router.post("/crypto/share", response_model=Dict[str, Dict[str, Any]], status_code=201)
async def create_crypto_share_link(
    share_data: CryptoShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate a shareable link to the crypto portfolio view.

    The link records the date window it was generated for, so the recipient
    sees the same range the owner was looking at.
    """
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    try:
        window = resolve_window(
            time_range=share_data.time_range or ("30d" if not share_data.start_date else None),
            start_date=share_data.start_date,
            end_date=share_data.end_date,
        )
    except ValueError as exc:
        raise BadRequestException(str(exc), code="INVALID_TIME_RANGE")

    # Absolute URL — a relative path can't be opened straight from the
    # clipboard. Points at the frontend page, which resolves the data via
    # GET /api/v1/portfolio/crypto/shared?code=...
    access_code = secrets.token_urlsafe(24)
    base_url = settings.FRONTEND_BASE_URL.rstrip("/")
    share_link = f"{base_url}/portfolio/crypto/shared?code={access_code}"

    expires_at = None
    if share_data.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=share_data.expires_in_days)

    share = PortfolioShare(
        account_id=account.id,
        view="crypto",
        share_link=share_link,
        access_code=access_code,
        email=share_data.email,
        expires_at=expires_at,
        window={
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            "time_range": share_data.time_range,
        },
    )
    db.add(share)
    await db.commit()
    await db.refresh(share)

    logger.info(f"Crypto share link created for account {account.id}: {share.id}")
    return {
        "data": {
            "id": str(share.id),
            "share_link": share_link,
            "access_code": access_code,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "window": share.window,
        }
    }


@router.get("/crypto/share", response_model=Dict[str, List[Dict[str, Any]]])
async def list_crypto_share_links(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List the crypto share links this account has generated."""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    result = await db.execute(
        select(PortfolioShare)
        .where(
            and_(
                PortfolioShare.account_id == account.id,
                PortfolioShare.view == "crypto",
            )
        )
        .order_by(desc(PortfolioShare.created_at))
    )
    shares = result.scalars().all()

    now = datetime.now(timezone.utc)
    return {
        "data": [
            {
                "id": str(share.id),
                "share_link": share.share_link,
                "email": share.email,
                "expires_at": share.expires_at.isoformat() if share.expires_at else None,
                "is_active": share.is_active,
                "is_expired": bool(
                    share.expires_at and _as_aware_utc(share.expires_at) < now
                ),
                "created_at": share.created_at.isoformat() if share.created_at else None,
            }
            for share in shares
        ]
    }


@router.delete("/crypto/share/{share_id}", response_model=Dict[str, Dict[str, Any]])
async def revoke_crypto_share_link(
    share_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate a share link. Revoked links resolve as 404, like unknown codes."""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    result = await db.execute(
        select(PortfolioShare).where(
            and_(
                PortfolioShare.id == share_id,
                PortfolioShare.account_id == account.id,
            )
        )
    )
    share = result.scalar_one_or_none()
    if share is None:
        raise NotFoundException("Share link", str(share_id))

    share.is_active = False
    await db.commit()

    return {"data": {"id": str(share_id), "is_active": False}}


@public_router.get("/crypto/shared", response_model=Dict[str, Any])
async def get_shared_crypto_portfolio(
    code: str = Query(..., description="Share access code from the share link"),
    db: AsyncSession = Depends(get_db)
):
    """Resolve a crypto portfolio share link.

    Anonymous by design — the per-share access code IS the credential, so this
    lives on public_router (no auth, no KYC gate) and declares no user
    dependency, which also means a stale Authorization header is never
    inspected. Contract matches GET /assets/{id}/shared: valid code → 200,
    unknown or revoked → 404, expired → 410 SHARE_LINK_EXPIRED.
    """
    result = await db.execute(
        select(PortfolioShare).where(
            and_(
                PortfolioShare.access_code == code,
                PortfolioShare.view == "crypto",
                PortfolioShare.is_active == True,
            )
        )
    )
    share = result.scalar_one_or_none()
    if share is None:
        raise NotFoundException("Share link", code)

    if share.expires_at and _as_aware_utc(share.expires_at) < datetime.now(timezone.utc):
        raise GoneException("This share link has expired.", code="SHARE_LINK_EXPIRED")

    account_result = await db.execute(
        select(Account).where(Account.id == share.account_id)
    )
    account = account_result.scalar_one_or_none()
    if account is None:
        raise NotFoundException("Share link", code)

    stored = share.window or {}
    try:
        window = resolve_window(
            start_date=datetime.fromisoformat(stored["start"]),
            end_date=datetime.fromisoformat(stored["end"]),
        )
    except (KeyError, TypeError, ValueError):
        window = resolve_window(time_range="30d")

    snapshot = await _crypto_snapshot(db, account, window)
    return {
        "data": {
            **snapshot,
            "shared_with": share.email,
            "window": stored,
            "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        }
    }


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

    # In-app transfers count as outflow for the period (QA B4).
    period_transfers = await db.execute(
        select(Transfer).where(
            and_(
                Transfer.account_id == account.id,
                Transfer.transfer_date >= start_date_obj.date(),
                Transfer.transfer_date <= end_date_obj.date(),
            )
        )
    )
    for transfer in period_transfers.scalars().all():
        total_outflow += transfer.amount

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
    
    # Transfers initiated in-app join the feed (QA B4: they used to vanish).
    transfers_result = await db.execute(
        select(Transfer).where(
            and_(
                Transfer.account_id == account.id,
                Transfer.transfer_date >= start_date_obj.date(),
                Transfer.transfer_date <= end_date_obj.date(),
            )
        )
    )
    linked_names = {str(la.id): la.account_name for la in linked_accounts}
    for transfer in transfers_result.scalars().all():
        entry = {
            "id": str(transfer.id),
            "date": transfer.transfer_date.isoformat(),
            "category": "Transfer",
            "amount": float(transfer.amount),
            "type": "outflow",
            "account": linked_names.get(str(transfer.from_linked_account_id), "Transfer"),
            "account_id": str(transfer.from_linked_account_id) if transfer.from_linked_account_id else None,
            "notes": transfer.description or f"{transfer.transfer_type.title()} transfer",
            "currency": transfer.currency,
            "status": transfer.status,
        }
        if type == "inflow":
            continue  # transfers out of a bank account are outflows
        if category and category != "Transfer":
            continue
        if min_amount and transfer.amount < min_amount:
            continue
        if max_amount and transfer.amount > max_amount:
            continue
        all_transactions.append(entry)

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

    if transfer_data.amount is None or transfer_data.amount <= 0:
        raise BadRequestException("amount must be positive")

    try:
        transfer_date = datetime.strptime(transfer_data.transfer_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise BadRequestException("transfer_date must be YYYY-MM-DD")

    def _resolve_linked(raw_id: Optional[str]) -> Optional[LinkedAccount]:
        """Match a request account id against the caller's linked accounts."""
        if not raw_id:
            return None
        try:
            wanted = UUID(str(raw_id))
        except ValueError:
            return None
        for linked in own_linked_accounts:
            if linked.id == wanted:
                return linked
        return None

    own_linked_result = await db.execute(
        select(LinkedAccount).where(LinkedAccount.account_id == account.id)
    )
    own_linked_accounts = own_linked_result.scalars().all()

    from_linked = None
    to_linked = None
    if transfer_data.transfer_type == "internal":
        from_linked = _resolve_linked(transfer_data.from_account_id)
        if from_linked is None:
            raise NotFoundException("Source account", str(transfer_data.from_account_id))
        to_linked = _resolve_linked(transfer_data.to_account_id)  # may be a wallet label -> None
    else:
        # External transfers drain a linked source account too — resolve it so
        # the balance check below applies (contract: 404 for unknown ids,
        # INSUFFICIENT_FUNDS when amount exceeds the balance).
        if transfer_data.from_account_id:
            from_linked = _resolve_linked(transfer_data.from_account_id)
            if from_linked is None:
                raise NotFoundException("Source account", str(transfer_data.from_account_id))

    # Balance check against the Plaid-synced balance of the source account.
    if from_linked is not None and from_linked.balance is not None:
        if Decimal(from_linked.balance) < transfer_data.amount:
            raise BadRequestException(
                "Insufficient funds in the source account for this transfer.",
                code="INSUFFICIENT_FUNDS",
            )

    transfer = Transfer(
        account_id=account.id,
        transfer_type=transfer_data.transfer_type,
        from_linked_account_id=from_linked.id if from_linked else None,
        to_linked_account_id=to_linked.id if to_linked else None,
        wallet_address=transfer_data.wallet_address,
        amount=transfer_data.amount,
        transfer_date=transfer_date,
        frequency=transfer_data.frequency or "one-time",
        description=transfer_data.description,
        status="pending",
        confirmation_number=f"FT{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
    )
    db.add(transfer)
    await db.commit()
    await db.refresh(transfer)

    return {
        "data": {
            "id": str(transfer.id),
            "status": transfer.status,
            "confirmation_number": transfer.confirmation_number,
            "created_at": transfer.created_at.isoformat() if transfer.created_at else datetime.utcnow().isoformat()
        }
    }


@router.get("/cash-flow/transfers/{transfer_id}", response_model=Dict[str, Dict[str, Any]])
async def get_transfer_status(
    transfer_id: str = Path(..., description="Transfer ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get transfer status (owner-scoped; unknown ids are 404, not fabricated)."""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    if not account:
        raise NotFoundException("Account", str(current_user.id))

    try:
        transfer_uuid = UUID(transfer_id)
    except ValueError:
        raise NotFoundException("Transfer", transfer_id)

    transfer_result = await db.execute(
        select(Transfer).where(
            and_(Transfer.id == transfer_uuid, Transfer.account_id == account.id)
        )
    )
    transfer = transfer_result.scalar_one_or_none()
    if not transfer:
        raise NotFoundException("Transfer", transfer_id)

    async def _linked_label(linked_id) -> Optional[str]:
        if not linked_id:
            return None
        linked = (
            await db.execute(select(LinkedAccount).where(LinkedAccount.id == linked_id))
        ).scalar_one_or_none()
        if not linked:
            return None
        masked = f" (****{linked.account_number[-4:]})" if linked.account_number else ""
        return f"{linked.account_name}{masked}"

    return {
        "data": {
            "id": str(transfer.id),
            "status": transfer.status,
            "confirmation_number": transfer.confirmation_number,
            "transfer_type": transfer.transfer_type,
            "from_account": await _linked_label(transfer.from_linked_account_id),
            "to_account": await _linked_label(transfer.to_linked_account_id) or transfer.wallet_address,
            "amount": float(transfer.amount),
            "currency": transfer.currency,
            "transfer_date": transfer.transfer_date.isoformat(),
            "description": transfer.description,
            "created_at": transfer.created_at.isoformat() if transfer.created_at else None
        }
    }


# ============================================================================
# TRADE ENGINE SECTION
# ============================================================================

@router.get("/trade-engine/search", response_model=Dict[str, List[Dict[str, Any]]])
async def search_assets(
    query: str = Query("", description="Search query — empty lists available instruments (browse mode)"),
    asset_class: str = Query("all", description="stocks, crypto, all"),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Search assets for trading.

    Exactly ONE Polygon call per search: the free-tier key allows 5 req/min,
    so per-result price lookups (2 extra calls each) made search return empty
    after the first couple of rows. Prices load when a result is selected
    (the details endpoint), not per search row. An empty query returns the
    market's instrument list so the UI can offer browseable options.
    """
    results = []

    # Polygon market filter beats client-side type filtering: crypto tickers
    # often carry no "type" at all, so the old type check dropped all of them.
    market_map = {"stocks": "stocks", "stock": "stocks", "etf": "stocks", "crypto": "crypto"}
    market = market_map.get(asset_class.lower()) if asset_class else None

    try:
        tickers = PolygonClient.search_tickers(query, limit=limit, market=market)
        if tickers:
            asset_type_map = {"cs": "Stock", "etp": "ETF", "bond": "Bond"}
            for ticker in tickers:
                ticker_symbol = ticker.get("ticker", "")
                ticker_market = (ticker.get("market") or "").lower()
                ticker_type = (ticker.get("type") or "").lower()

                if ticker_market == "crypto":
                    # Polygon prefixes crypto pairs (X:BTCUSD); brokerage and
                    # UI use the plain pair (BTCUSD).
                    display_symbol = ticker_symbol[2:] if ticker_symbol.startswith("X:") else ticker_symbol
                    display_type = "Crypto"
                else:
                    display_symbol = ticker_symbol
                    display_type = asset_type_map.get(ticker_type, "Stock")

                results.append({
                    "symbol": display_symbol,
                    "name": ticker.get("name", ""),
                    "type": display_type,
                    "currency": "USD"
                })
    except Exception as e:
        logger.error(f"Failed to search assets: {e}")

    return {"data": results[:limit]}


@router.get("/trade-engine/quotes", response_model=Dict[str, Dict[str, Any]])
async def get_batch_quotes(
    symbols: str = Query(..., description="Comma-separated symbols, max 20 (e.g. AAPL,MSFT,BTCUSD)"),
    current_user: User = Depends(get_current_user),
):
    """Batch price lookup for visible rows (QA B8: search results carry no
    price so search-driven UIs showed $0.00).

    Cached quotes are free; at most 3 UNCACHED symbols are fetched per call to
    respect the free-tier Polygon budget (5 req/min). Symbols that would
    exceed the budget return {"price": null} — the client re-requests later
    and hits the now-warm cache.
    """
    requested = [s.strip().upper() for s in symbols.split(",") if s.strip()][:20]
    if not requested:
        raise BadRequestException("symbols must contain at least one symbol")

    quotes: Dict[str, Any] = {}
    fresh_fetches = 0
    for symbol in requested:
        # Crypto pairs arrive plain (BTCUSD) but Polygon wants the X: prefix.
        candidates = [symbol] if symbol.startswith("X:") else [symbol, f"X:{symbol}"]
        quote = None
        for candidate in candidates:
            cached = PolygonClient.has_cached_price(candidate)
            if not cached:
                if fresh_fetches >= 3:
                    continue
                fresh_fetches += 1
            quote = _polygon_quote(candidate)
            if quote:
                break
        if quote:
            price, change, change_pct = quote
            quotes[symbol] = {
                "price": round(price, 2),
                "change": round(change, 2),
                "change_percentage": round(change_pct, 2),
            }
        else:
            quotes[symbol] = {"price": None}

    return {"quotes": quotes}


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
        
        # Crypto pairs arrive plain (BTCUSD) but Polygon wants the X: prefix —
        # retry before giving up so selecting a crypto search result works.
        if not current_price and not symbol_upper.startswith("X:"):
            crypto_ticker = f"X:{symbol_upper}"
            current_price = PolygonClient.get_current_price(crypto_ticker)
            if current_price:
                symbol_upper = crypto_ticker
                ticker_details = PolygonClient.get_ticker_details(crypto_ticker)

        if not current_price:
            raise NotFoundException("Asset", f"Symbol '{symbol}' not found or price unavailable")
        
        # The previous-day bar (cached, and already fetched inside
        # get_current_price on free-tier keys) has open+close — enough for the
        # day change. The old extra /v1/open-close call burned rate budget.
        prev_bar = PolygonClient.get_previous_close(symbol_upper)
        prev_results = (prev_bar or {}).get("results") or []
        day_open = prev_results[0].get("o") if prev_results else None
        prev_price = float(day_open) if day_open else current_price
        change = current_price - prev_price if prev_price else 0
        change_pct = (change / prev_price * 100) if prev_price > 0 else 0

        # Get additional data from snapshot
        bid = current_price
        ask = current_price
        volume = float(prev_results[0].get("v") or 0) if prev_results else 0
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
        
        # Get asset name from ticker details (fallback never shows the X: prefix)
        asset_name = symbol_upper[2:] if symbol_upper.startswith("X:") else symbol_upper
        if ticker_details and ticker_details.get("results"):
            asset_name = ticker_details["results"].get("name", asset_name)
        
        # Determine asset class
        if symbol_upper.startswith("X:"):
            asset_class = "crypto"
        elif ticker_details and ticker_details.get("results"):
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
                # Hand back the plain pair for crypto — the UI and brokerage
                # never see Polygon's X: prefix.
                "symbol": symbol_upper[2:] if symbol_upper.startswith("X:") else symbol_upper,
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


@router.get("/trade-engine/assets/{symbol}/price-history", response_model=Dict[str, List[Dict[str, Any]]])
async def get_asset_price_history(
    symbol: str = Path(..., description="Asset symbol"),
    time_range: str = Query("1M", alias="range", description="1D, 1W, 1M, 3M, 6M, 1Y, 5Y, ALL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Price candles for the asset chart — one Polygon aggregates call
    (works on the free-tier key). Crypto pairs retry with the X: prefix.

    Bar size scales with the window like a trading terminal: hourly bars for
    intraday/week views, daily up to a year, weekly/monthly beyond that.
    """
    symbol_upper = symbol.upper().strip()

    # range → (multiplier, timespan, lookback days). Lookbacks include indicator
    # WARM-UP periods beyond the display window (SMA50 etc. need ~50 prior bars
    # or they'd have nothing to draw on short ranges) — the frontend slices the
    # display window client-side and uses the earlier bars only for math.
    range_map = {
        "1D": (1, "hour", 7),
        "1W": (1, "hour", 14),
        "1M": (1, "day", 30 + 110),
        "3M": (1, "day", 90 + 110),
        "6M": (1, "day", 180 + 110),
        "1Y": (1, "day", 365 + 110),
        "5Y": (1, "week", 365 * 5 + 400),
        "ALL": (1, "month", 365 * 20),
    }
    multiplier, timespan, days = range_map.get(time_range.upper(), (1, "day", 30))
    to_date = datetime.utcnow().date()
    from_date = to_date - timedelta(days=days)

    def fetch(ticker: str):
        data = PolygonClient.get_aggregates(
            ticker, multiplier, timespan, from_date.isoformat(), to_date.isoformat()
        )
        return (data or {}).get("results") or []

    try:
        results = fetch(symbol_upper)
        if not results and not symbol_upper.startswith("X:"):
            results = fetch(f"X:{symbol_upper}")

        history = []
        for bar in results:
            if bar.get("t") is None:
                continue
            ts = datetime.utcfromtimestamp(bar["t"] / 1000)
            history.append({
                # Intraday bars keep the time component; daily+ bars are dates.
                "date": ts.isoformat() if timespan == "hour" else ts.date().isoformat(),
                "open": bar.get("o"),
                "high": bar.get("h"),
                "low": bar.get("l"),
                "close": bar.get("c"),
                "volume": bar.get("v"),
            })

        # All bars (warm-up included) go to the client — it trims the display
        # window itself so indicators can be computed over the full series.
        return {"data": history}
    except Exception as e:
        logger.error(f"Error getting price history for {symbol}: {e}", exc_info=True)
        return {"data": []}


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
    
    # Balance and buying power come from the caller's OWN cash ledger. They
    # used to be read off AlpacaClient.get_account(), but that client runs on
    # app-level credentials — one shared paper account, so every user saw the
    # same figure and it never reflected their own trades.
    cash_balance = apply_delta(account.cash_balance, 0)

    masked_number = "****"
    try:
        alpaca_account = AlpacaClient.get_account()
        if alpaca_account:
            raw_number = (
                alpaca_account.get("account_number", "")
                if isinstance(alpaca_account, dict)
                else getattr(alpaca_account, "account_number", "")
            )
            if raw_number:
                masked_number = f"****{str(raw_number)[-4:]}"
    except Exception as e:
        # Display detail only — never let the broker being down hide the balance.
        logger.error(f"Failed to get Alpaca account: {e}")

    return {
        "data": [
            {
                "id": str(account.id),
                "name": "Primary Trading Account",
                "masked_number": masked_number,
                "type": "brokerage",
                "balance": float(cash_balance),
                "buying_power": float(cash_balance),
                "currency": "USD",
            }
        ]
    }


class CashMovementRequest(BaseModel):
    linked_account_id: str = Field(..., description="A linked bank account belonging to the caller")
    amount: Decimal = Field(..., description="Positive amount in USD")
    description: Optional[str] = None


async def _resolve_own_linked_account(db: AsyncSession, account: Account, raw_id: str) -> LinkedAccount:
    """Caller-scoped lookup — an id belonging to someone else is a 404, not a 403."""
    try:
        wanted = UUID(str(raw_id))
    except (TypeError, ValueError):
        raise NotFoundException("Linked account", str(raw_id))

    result = await db.execute(
        select(LinkedAccount).where(
            and_(
                LinkedAccount.id == wanted,
                LinkedAccount.account_id == account.id,
                LinkedAccount.is_active == True,
            )
        )
    )
    linked = result.scalar_one_or_none()
    if linked is None:
        raise NotFoundException("Linked account", str(raw_id))
    return linked


@router.get("/trade-engine/cash", response_model=Dict[str, Dict[str, Any]])
async def get_trading_cash(
    limit: int = Query(20, ge=1, le=100, description="Recent ledger entries to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Settled trading cash plus the recent ledger entries behind it."""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    entries_result = await db.execute(
        select(CashTransaction)
        .where(CashTransaction.account_id == account.id)
        .order_by(desc(CashTransaction.created_at))
        .limit(limit)
    )
    entries = entries_result.scalars().all()

    return {
        "data": {
            "cash_balance": float(apply_delta(account.cash_balance, 0)),
            "currency": "USD",
            "transactions": [
                {
                    "id": str(entry.id),
                    "entry_type": entry.entry_type.value,
                    "amount": float(entry.amount),
                    "balance_after": float(entry.balance_after),
                    "description": entry.description,
                    "order_id": str(entry.order_id) if entry.order_id else None,
                    "created_at": entry.created_at.isoformat() if entry.created_at else None,
                }
                for entry in entries
            ],
        }
    }


@router.post("/trade-engine/cash/deposit", response_model=Dict[str, Dict[str, Any]])
async def deposit_trading_cash(
    request: CashMovementRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Move money from a linked bank account into trading cash."""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    if request.amount is None or request.amount <= 0:
        raise BadRequestException("amount must be positive")

    linked = await _resolve_own_linked_account(db, account, request.linked_account_id)

    # Same convention as /cash-flow/transfers: only enforce when Plaid has
    # actually given us a balance to check against.
    if linked.balance is not None and Decimal(linked.balance) < request.amount:
        raise BadRequestException(
            "Insufficient funds in the source account for this deposit.",
            code="INSUFFICIENT_FUNDS",
        )

    if linked.balance is not None:
        linked.balance = Decimal(linked.balance) - request.amount

    await record_cash_movement(
        db,
        account,
        entry_type=CashEntryType.DEPOSIT,
        delta=request.amount,
        description=request.description or f"Deposit from {linked.account_name or 'linked account'}",
        linked_account_id=linked.id,
    )
    await db.commit()
    await db.refresh(account)

    return {
        "data": {
            "cash_balance": float(apply_delta(account.cash_balance, 0)),
            "source_account_balance": float(linked.balance) if linked.balance is not None else None,
            "amount": float(request.amount),
            "currency": "USD",
        }
    }


@router.post("/trade-engine/cash/withdraw", response_model=Dict[str, Dict[str, Any]])
async def withdraw_trading_cash(
    request: CashMovementRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Move settled trading cash back out to a linked bank account."""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    if request.amount is None or request.amount <= 0:
        raise BadRequestException("amount must be positive")

    linked = await _resolve_own_linked_account(db, account, request.linked_account_id)

    if not has_sufficient_funds(account.cash_balance, -request.amount):
        raise BadRequestException(
            f"Insufficient trading cash for this withdrawal. Balance "
            f"{apply_delta(account.cash_balance, 0)}.",
            code="INSUFFICIENT_FUNDS",
        )

    if linked.balance is not None:
        linked.balance = Decimal(linked.balance) + request.amount

    await record_cash_movement(
        db,
        account,
        entry_type=CashEntryType.WITHDRAWAL,
        delta=-request.amount,
        description=request.description or f"Withdrawal to {linked.account_name or 'linked account'}",
        linked_account_id=linked.id,
    )
    await db.commit()
    await db.refresh(account)

    return {
        "data": {
            "cash_balance": float(apply_delta(account.cash_balance, 0)),
            "destination_account_balance": float(linked.balance) if linked.balance is not None else None,
            "amount": float(request.amount),
            "currency": "USD",
        }
    }


class OrderRequest(BaseModel):
    symbol: str
    order_type: str = Field(..., description="buy or sell")
    order_mode: str = Field(..., description="market, limit, or stop-limit")
    quantity: Decimal
    limit_price: Optional[Decimal] = Field(None, description="Required for limit and stop-limit orders")
    stop_price: Optional[Decimal] = Field(None, description="Required for stop-limit orders")
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
    
    # Normalize and validate the order mode ("stop_limit" tolerated as alias)
    mode = (order_data.order_mode or "").lower().replace("_", "-")
    if mode not in ("market", "limit", "stop-limit"):
        raise BadRequestException("order_mode must be 'market', 'limit', or 'stop-limit'")
    if mode == "limit" and not order_data.limit_price:
        raise BadRequestException("limit_price required for limit orders")
    if mode == "stop-limit" and (not order_data.limit_price or not order_data.stop_price):
        raise BadRequestException("stop_price and limit_price required for stop-limit orders")

    if order_data.quantity is None or order_data.quantity <= 0:
        raise BadRequestException("quantity must be positive")

    if (order_data.order_type or "").strip().lower() not in ("buy", "sell"):
        raise BadRequestException("order_type must be 'buy' or 'sell'")

    # Price the order BEFORE touching the broker so an unaffordable order is
    # rejected here rather than filled at Alpaca and then refused locally.
    # (QA B6: orders were stored with price 0 and every downstream feed showed
    # "$0.00" trades — same price source as the asset-details endpoint, crypto
    # X: retry included.)
    execution_price = None
    if mode in ("limit", "stop-limit"):
        execution_price = order_data.limit_price
    else:
        try:
            symbol_upper = order_data.symbol.upper().strip()
            quote = PolygonClient.get_current_price(symbol_upper)
            if not quote and not symbol_upper.startswith("X:"):
                quote = PolygonClient.get_current_price(f"X:{symbol_upper}")
            if quote:
                execution_price = Decimal(str(quote))
        except Exception as price_err:  # a quote miss must never fail the order
            logger.warning(f"No execution price for {order_data.symbol}: {price_err}")

    # Funds check against the caller's own trading cash. Runs for queued orders
    # too — you cannot place an order you could not pay for — but only settled
    # (priced) orders actually move cash below.
    cash_delta = order_cash_delta(order_data.order_type, order_data.quantity, execution_price)
    if not has_sufficient_funds(account.cash_balance, cash_delta):
        raise BadRequestException(
            f"Insufficient trading cash for this order. Balance "
            f"{apply_delta(account.cash_balance, 0)}, order requires "
            f"{order_notional(order_data.quantity, execution_price)}.",
            code="INSUFFICIENT_FUNDS",
        )

    # Create order via Alpaca
    try:
        if mode == "market":
            alpaca_order = AlpacaClient.create_market_order(
                symbol=order_data.symbol,
                qty=float(order_data.quantity),
                side=order_data.order_type
            )
        elif mode == "stop-limit":
            alpaca_order = AlpacaClient.create_stop_limit_order(
                symbol=order_data.symbol,
                qty=float(order_data.quantity),
                side=order_data.order_type,
                stop_price=float(order_data.stop_price),
                limit_price=float(order_data.limit_price)
            )
        else:  # limit
            alpaca_order = AlpacaClient.create_limit_order(
                symbol=order_data.symbol,
                qty=float(order_data.quantity),
                side=order_data.order_type,
                limit_price=float(order_data.limit_price)
            )

        if not alpaca_order:
            # Surface the broker's reject reason (wash-trade guard, insufficient
            # qty, market closed, …) instead of a blind "failed".
            broker_error = getattr(AlpacaClient, "_last_order_error", None)
            detail = f": {broker_error}" if broker_error else ""
            raise BadRequestException(f"Broker rejected the order{detail}")

        is_market = mode == "market"
        filled = is_market and execution_price is not None

        # Save order to database. Stop-limit persists as STOP (closest enum
        # value — the stop trigger defines the order); Alpaca holds full detail.
        db_order_type = (
            OrderType.MARKET if is_market
            else OrderType.STOP if mode == "stop-limit"
            else OrderType.LIMIT
        )
        order = Order(
            account_id=account.id,
            order_type=db_order_type,
            symbol=order_data.symbol,
            quantity=order_data.quantity,
            price=execution_price,
            side=order_data.order_type,
            status=OrderStatus.FILLED if filled else OrderStatus.SUBMITTED,
            filled_quantity=order_data.quantity if filled else 0,
            filled_price=execution_price if filled else None,
            alpaca_order_id=str(alpaca_order.get("id", "")) if isinstance(alpaca_order, dict) else str(getattr(alpaca_order, "id", ""))
        )
        db.add(order)
        # Flush (not commit) so the ledger row can reference order.id and both
        # land in the same transaction as the balance change.
        await db.flush()

        # Only settled orders move cash. A SUBMITTED order has no fill to
        # settle, and nothing in this codebase syncs Alpaca fills back into
        # `orders` yet — see app/services/cash_ledger.py.
        if filled and cash_delta != Decimal("0.00"):
            await record_cash_movement(
                db,
                account,
                entry_type=(
                    CashEntryType.TRADE_BUY if cash_delta < 0 else CashEntryType.TRADE_SELL
                ),
                delta=cash_delta,
                description=f"{order_data.order_type.lower()} {order_data.quantity} {order_data.symbol.upper()}",
                order_id=order.id,
            )

        await db.commit()
        await db.refresh(order)
        await db.refresh(account)

        order_id = str(alpaca_order.get("id", "")) if isinstance(alpaca_order, dict) else str(getattr(alpaca_order, "id", ""))
        estimated_total = float(order_data.quantity * (execution_price or 0))

        return {
            "data": {
                "order_id": order_id,
                "status": order.status.value,
                "confirmation_number": f"ORD{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                "price": float(execution_price) if execution_price is not None else None,
                "estimated_total": estimated_total,
                # The caller's own cash after this order, so the trade screen
                # can update without a second round-trip.
                "cash_balance": float(apply_delta(account.cash_balance, 0)),
                "created_at": datetime.utcnow().isoformat()
            }
        }
    except BadRequestException:
        # Broker rejects already carry their own message/code — re-wrapping
        # them buried the reason behind a generic "Failed to place order".
        raise
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

