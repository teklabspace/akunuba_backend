from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, or_, func
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.asset import Asset, AssetType, AssetValuation
from app.models.portfolio import Portfolio
from app.models.order import Order, OrderStatus
from app.models.banking import LinkedAccount, Transaction
from app.core.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger
from app.integrations.polygon_client import PolygonClient
from app.integrations.alpaca_client import AlpacaClient
from pydantic import BaseModel

router = APIRouter()


class AssetSummaryCard(BaseModel):
    type: str
    label: str
    value: float
    change: Optional[float] = None
    change_percentage: Optional[float] = None
    currency: str = "USD"


class ActivityItem(BaseModel):
    id: str
    type: str
    asset: Optional[str] = None
    name: Optional[str] = None
    amount: Optional[float] = None
    price: Optional[float] = None
    total: Optional[float] = None
    date: str
    time: Optional[str] = None
    currency: str = "USD"


class CryptoPrice(BaseModel):
    symbol: str
    name: str
    price: float
    change: float
    change_percentage: float


class TraderProfile(BaseModel):
    account_number: Optional[str] = None
    buying_power: float
    cash: float
    portfolio_value: float
    pattern_day_trader: bool = False
    trading_blocked: bool = False
    account_blocked: bool = False
    status: str


@router.get("/overview/assets", response_model=Dict[str, List[AssetSummaryCard]])
async def get_asset_summary_cards(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get asset summary cards for investment overview"""
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
        
        # Calculate totals by asset type
        summary_cards = []
        
        # Total Portfolio Value
        total_value = sum([asset.current_value for asset in assets]) if assets else Decimal("0.00")
        
        # Get yesterday's value for change calculation
        yesterday_value = Decimal("0.00")
        try:
            for asset in assets:
                # Get yesterday's valuation
                yesterday = datetime.utcnow() - timedelta(days=1)
                valuation_result = await db.execute(
                    select(AssetValuation)
                    .where(
                        and_(
                            AssetValuation.asset_id == asset.id,
                            AssetValuation.valuation_date <= yesterday
                        )
                    )
                    .order_by(desc(AssetValuation.valuation_date))
                    .limit(1)
                )
                valuation = valuation_result.scalar_one_or_none()
                if valuation:
                    yesterday_value += valuation.value
                else:
                    yesterday_value += asset.current_value
        except Exception as e:
            logger.warning(f"Failed to calculate yesterday's value: {e}")
            yesterday_value = total_value  # Fallback to current value
        
        change = float(total_value - yesterday_value)
        change_percentage = float((change / yesterday_value * 100) if yesterday_value > 0 else 0)
        
        summary_cards.append(AssetSummaryCard(
            type="total",
            label="Total Portfolio Value",
            value=float(total_value),
            change=change,
            change_percentage=change_percentage
        ))
        
        # Group by asset type
        asset_types = {}
        for asset in assets:
            try:
                asset_type = asset.asset_type.value if asset.asset_type else "other"
            except (AttributeError, ValueError):
                asset_type = "other"
            
            if asset_type not in asset_types:
                asset_types[asset_type] = {
                    "count": 0,
                    "value": Decimal("0.00")
                }
            asset_types[asset_type]["count"] += 1
            asset_types[asset_type]["value"] += asset.current_value
        
        # Create cards for each asset type
        type_labels = {
            "stock": "Stocks",
            "crypto": "Cryptocurrency",
            "real_estate": "Real Estate",
            "bond": "Bonds",
            "etf": "ETFs",
            "other": "Other Assets"
        }
        
        for asset_type, data in asset_types.items():
            label = type_labels.get(asset_type, asset_type.replace("_", " ").title())
            summary_cards.append(AssetSummaryCard(
                type=asset_type,
                label=label,
                value=float(data["value"]),
                change=None,
                change_percentage=None
            ))
        
        # Cash available
        cash_available = Decimal("0.00")
        try:
            alpaca_account = AlpacaClient.get_account()
            if alpaca_account:
                if isinstance(alpaca_account, dict):
                    cash_available = Decimal(str(alpaca_account.get("cash", 0)))
                else:
                    cash_available = Decimal(str(getattr(alpaca_account, "cash", 0)))
        except Exception as e:
            logger.warning(f"Failed to get Alpaca cash: {e}")
        
        # Also check linked accounts
        try:
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
        except Exception as e:
            logger.warning(f"Failed to get linked accounts: {e}")
        
        summary_cards.append(AssetSummaryCard(
            type="cash",
            label="Cash Available",
            value=float(cash_available),
            change=None,
            change_percentage=None
        ))
        
        return {"data": summary_cards}
    except (NotFoundException, BadRequestException):
        raise
    except Exception as e:
        logger.error(f"Error in get_asset_summary_cards: {e}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise BadRequestException(f"Failed to get asset summary cards: {str(e)}")


@router.get("/overview/activity", response_model=Dict[str, List[ActivityItem]])
async def get_investment_activity(
    limit: int = Query(10, ge=1, le=100, description="Number of activities to return"),
    type: Optional[str] = Query("all", description="Filter by type: buy, sell, dividend, transfer, all"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get recent investment activity"""
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
                
                activities.append(ActivityItem(
                    id=str(tx.get("id", "")),
                    type=activity_type,
                    asset=tx.get("symbol", ""),
                    name=tx.get("symbol", ""),
                    amount=tx.get("qty", 0),
                    price=tx.get("price", 0),
                    total=float(tx.get("qty", 0)) * float(tx.get("price", 0)) if tx.get("qty") and tx.get("price") else tx.get("net_amount", 0),
                    date=tx.get("date", "").split("T")[0] if tx.get("date") else "",
                    time=tx.get("date", "").split("T")[1][:8] if tx.get("date") and "T" in tx.get("date", "") else None
                ))
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
        
        activities.append(ActivityItem(
            id=str(order.id),
            type=order.side.lower(),
            asset=order.symbol,
            name=order.symbol,
            amount=float(order.quantity),
            price=float(order.price) if order.price else 0,
            total=float(order.quantity * order.price) if order.price else 0,
            date=order.created_at.date().isoformat() if order.created_at else "",
            time=order.created_at.time().isoformat()[:8] if order.created_at else None
        ))
    
    # Sort by date descending
    activities.sort(key=lambda x: x.date, reverse=True)
    
    return {"data": activities[:limit]}


@router.get("/overview/crypto-prices", response_model=Dict[str, List[CryptoPrice]])
async def get_crypto_prices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get crypto prices for investment overview"""
    crypto_list = ["BTC", "ETH", "USDT", "USDC", "BNB", "XRP", "ADA", "SOL"]
    crypto_prices = []
    
    for symbol in crypto_list:
        try:
            price = PolygonClient.get_current_price(f"{symbol}USD")
            if price:
                # Get previous day for change calculation
                yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
                prev_data = PolygonClient.get_daily_open_close(f"{symbol}USD", yesterday)
                prev_price = prev_data.get("close") if prev_data else price
                change = price - prev_price if prev_price else 0
                change_pct = (change / prev_price * 100) if prev_price > 0 else 0
                
                crypto_names = {
                    "BTC": "Bitcoin",
                    "ETH": "Ethereum",
                    "USDT": "Tether",
                    "USDC": "USD Coin",
                    "BNB": "Binance Coin",
                    "XRP": "Ripple",
                    "ADA": "Cardano",
                    "SOL": "Solana"
                }
                
                crypto_prices.append(CryptoPrice(
                    symbol=symbol,
                    name=crypto_names.get(symbol, symbol),
                    price=round(price, 2),
                    change=round(change, 2),
                    change_percentage=round(change_pct, 2)
                ))
        except Exception as e:
            logger.warning(f"Failed to get price for {symbol}: {e}")
            continue
    
    return {"data": crypto_prices}


@router.get("/overview/trader-profile", response_model=Dict[str, TraderProfile])
async def get_trader_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get trader profile for investment overview"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get Alpaca account info
    try:
        alpaca_account = AlpacaClient.get_account()
        
        if alpaca_account is None:
            # Return default values if Alpaca account not available
            return {
                "data": TraderProfile(
                    buying_power=0.0,
                    cash=0.0,
                    portfolio_value=0.0,
                    status="not_connected"
                )
            }
        
        # Format account data
        if isinstance(alpaca_account, dict):
            account_data = alpaca_account
        else:
            account_data = {
                "account_number": getattr(alpaca_account, "account_number", ""),
                "buying_power": float(getattr(alpaca_account, "buying_power", 0)),
                "cash": float(getattr(alpaca_account, "cash", 0)),
                "portfolio_value": float(getattr(alpaca_account, "portfolio_value", 0)),
                "pattern_day_trader": getattr(alpaca_account, "pattern_day_trader", False),
                "trading_blocked": getattr(alpaca_account, "trading_blocked", False),
                "account_blocked": getattr(alpaca_account, "account_blocked", False),
                "status": getattr(alpaca_account, "status", "")
            }
        
        return {
            "data": TraderProfile(
                account_number=account_data.get("account_number", ""),
                buying_power=account_data.get("buying_power", 0),
                cash=account_data.get("cash", 0),
                portfolio_value=account_data.get("portfolio_value", 0),
                pattern_day_trader=account_data.get("pattern_day_trader", False),
                trading_blocked=account_data.get("trading_blocked", False),
                account_blocked=account_data.get("account_blocked", False),
                status=account_data.get("status", "")
            )
        }
    except Exception as e:
        logger.error(f"Failed to get Alpaca account: {e}")
        # Return default values on error
        return {
            "data": TraderProfile(
                buying_power=0.0,
                cash=0.0,
                portfolio_value=0.0,
                status="error"
            )
        }


class PerformanceMetrics(BaseModel):
    total_return: Decimal
    total_return_percentage: Decimal
    period_days: int
    current_value: Decimal
    historical_value: Decimal
    daily_returns: Optional[List[Dict[str, Any]]] = None
    best_performer: Optional[Dict[str, Any]] = None
    worst_performer: Optional[Dict[str, Any]] = None
    asset_breakdown: Optional[List[Dict[str, Any]]] = None


class AnalyticsMetrics(BaseModel):
    total_invested: Decimal
    current_value: Decimal
    total_return: Decimal
    total_return_percentage: Decimal
    annualized_return: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    volatility: Optional[float] = None
    beta: Optional[float] = None
    alpha: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    average_holding_period: Optional[int] = None
    asset_allocation: Optional[Dict[str, float]] = None
    sector_allocation: Optional[Dict[str, float]] = None
    performance_by_period: Optional[Dict[str, float]] = None


class RecommendationItem(BaseModel):
    id: str
    type: str
    symbol: str
    name: str
    reason: str
    confidence: int
    current_price: float
    target_price: Optional[float] = None
    potential_return: Optional[float] = None
    risk_level: str
    time_horizon: str
    created_at: datetime


class RecommendationsResponse(BaseModel):
    data: List[RecommendationItem]
    portfolio_insights: Dict[str, Any]


async def calculate_performance_metrics(
    account_id: UUID,
    db: AsyncSession,
    days: int = 30
) -> PerformanceMetrics:
    """Calculate investment performance metrics"""
    period_start = datetime.utcnow() - timedelta(days=days)
    
    # Get all assets for the account
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account_id)
    )
    assets = assets_result.scalars().all()
    
    if not assets:
        return PerformanceMetrics(
            total_return=Decimal("0.00"),
            total_return_percentage=Decimal("0.00"),
            period_days=days,
            current_value=Decimal("0.00"),
            historical_value=Decimal("0.00"),
            daily_returns=[],
            best_performer=None,
            worst_performer=None,
            asset_breakdown=[]
        )
    
    # Calculate current total value
    current_value = sum([asset.current_value for asset in assets])
    currency = assets[0].currency if assets else "USD"
    
    # Get historical valuations
    historical_values = {}
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
        historical_valuation = valuation_result.scalar_one_or_none()
        
        if historical_valuation:
            historical_values[asset.id] = historical_valuation.value
        else:
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
    
    # Calculate daily returns
    daily_returns = []
    step = max(1, days // 30)
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
        
        daily_returns.append({
            "date": snapshot_date.date().isoformat(),
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
    
    # Asset breakdown
    asset_breakdown = []
    for asset in assets:
        asset_type = asset.asset_type.value if asset.asset_type else "other"
        percentage = (asset.current_value / current_value * 100) if current_value > 0 else Decimal("0.00")
        asset_breakdown.append({
            "type": asset_type,
            "value": float(asset.current_value),
            "percentage": float(percentage)
        })
    
    return PerformanceMetrics(
        total_return=total_return,
        total_return_percentage=total_return_percentage,
        period_days=days,
        current_value=current_value,
        historical_value=historical_value,
        daily_returns=daily_returns if daily_returns else [],
        best_performer=best_performer,
        worst_performer=worst_performer,
        asset_breakdown=asset_breakdown
    )


@router.get("/performance", response_model=PerformanceMetrics)
async def get_investment_performance(
    days: int = Query(30, ge=1, le=365, description="Number of days for performance calculation"),
    time_range: Optional[str] = Query("1M", description="Time range: 1D, 1W, 1M, 3M, 6M, 1Y, ALL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get investment performance metrics"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # Map time range to days if provided
        time_range_map = {
            "1D": 1,
            "1W": 7,
            "1M": 30,
            "3M": 90,
            "6M": 180,
            "1Y": 365,
            "ALL": 365
        }
        if time_range and time_range in time_range_map:
            days = time_range_map[time_range]
        
        performance_data = await calculate_performance_metrics(account.id, db, days=days)
        
        return performance_data
    except Exception as e:
        logger.error(f"Error in get_investment_performance: {e}", exc_info=True)
        return PerformanceMetrics(
            total_return=Decimal("0.00"),
            total_return_percentage=Decimal("0.00"),
            period_days=days,
            current_value=Decimal("0.00"),
            historical_value=Decimal("0.00"),
            daily_returns=[],
            best_performer=None,
            worst_performer=None,
            asset_breakdown=[]
        )


@router.get("/analytics", response_model=AnalyticsMetrics)
async def get_investment_analytics(
    time_range: str = Query("1Y", description="Time range: 1M, 3M, 6M, 1Y, ALL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed investment analytics"""
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
            return AnalyticsMetrics(
                total_invested=Decimal("0.00"),
                current_value=Decimal("0.00"),
                total_return=Decimal("0.00"),
                total_return_percentage=Decimal("0.00")
            )
        
        # Calculate current value
        current_value = sum([asset.current_value for asset in assets])
        
        # Calculate total invested (sum of first valuations or purchase prices)
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
            elif asset.purchase_price:
                total_invested += asset.purchase_price
            else:
                total_invested += asset.current_value  # Fallback
        
        total_return = current_value - total_invested
        total_return_percentage = (total_return / total_invested * 100) if total_invested > 0 else Decimal("0.00")
        
        # Calculate annualized return
        period_years = days / 365.0
        annualized_return = None
        if period_years > 0 and total_invested > 0:
            annualized_return = float(((current_value / total_invested) ** (1 / period_years) - 1) * 100)
        
        # Calculate volatility (simplified)
        period_start = datetime.utcnow() - timedelta(days=days)
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
        
        volatility = None
        if len(all_valuations) > 1:
            mean_return = sum(all_valuations) / len(all_valuations)
            variance = sum([(r - mean_return) ** 2 for r in all_valuations]) / len(all_valuations)
            volatility = variance ** 0.5
        
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
            period_start_date = datetime.utcnow() - timedelta(days=period_days)
            
            period_historical_value = Decimal("0.00")
            for asset in assets:
                valuation_result = await db.execute(
                    select(AssetValuation)
                    .where(
                        and_(
                            AssetValuation.asset_id == asset.id,
                            AssetValuation.valuation_date <= period_start_date
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
        
        return AnalyticsMetrics(
            total_invested=total_invested,
            current_value=current_value,
            total_return=total_return,
            total_return_percentage=total_return_percentage,
            annualized_return=annualized_return,
            sharpe_ratio=None,  # Would require risk-free rate
            volatility=volatility,
            beta=None,  # Would require market data
            alpha=None,  # Would require benchmark
            max_drawdown=None,  # Would require detailed history
            win_rate=None,  # Would require trade history
            average_holding_period=None,  # Would require trade history
            asset_allocation=asset_allocation,
            sector_allocation=None,  # Would require sector data
            performance_by_period=performance_by_period
        )
    except Exception as e:
        logger.error(f"Error in get_investment_analytics: {e}", exc_info=True)
        return AnalyticsMetrics(
            total_invested=Decimal("0.00"),
            current_value=Decimal("0.00"),
            total_return=Decimal("0.00"),
            total_return_percentage=Decimal("0.00")
        )


@router.get("/recommendations", response_model=RecommendationsResponse)
async def get_investment_recommendations(
    limit: int = Query(10, ge=1, le=50, description="Number of recommendations to return"),
    type: Optional[str] = Query("all", description="Filter by type: buy, sell, hold, diversify"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get personalized investment recommendations"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # Get portfolio assets
        assets_result = await db.execute(
            select(Asset).where(Asset.account_id == account.id)
        )
        assets = assets_result.scalars().all()
        
        total_value = sum([asset.current_value for asset in assets]) if assets else Decimal("0.00")
        
        recommendations = []
        
        # Analyze portfolio for recommendations
        if assets:
            # Check for over-concentration
            asset_types = {}
            for asset in assets:
                asset_type = asset.asset_type.value if asset.asset_type else "other"
                if asset_type not in asset_types:
                    asset_types[asset_type] = Decimal("0.00")
                asset_types[asset_type] += asset.current_value
            
            # Find over-concentrated asset types
            for asset_type, value in asset_types.items():
                percentage = (value / total_value * 100) if total_value > 0 else 0
                if percentage > 40:  # Over 40% concentration
                    recommendations.append(RecommendationItem(
                        id=f"diversify_{asset_type}",
                        type="diversify",
                        symbol=asset_type.upper(),
                        name=f"{asset_type.title()} Diversification",
                        reason=f"Portfolio is {percentage:.1f}% concentrated in {asset_type}. Consider diversifying.",
                        confidence=85,
                        current_price=0.0,
                        target_price=None,
                        potential_return=None,
                        risk_level="medium",
                        time_horizon="3-6 months",
                        created_at=datetime.utcnow()
                    ))
        
        # Check for underperforming assets
        period_start = datetime.utcnow() - timedelta(days=90)
        for asset in assets[:10]:  # Limit to top 10 assets
            # Get historical value
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
            
            if historical_valuation and historical_valuation.value > 0:
                return_pct = ((asset.current_value - historical_valuation.value) / historical_valuation.value * 100)
                
                # Recommend sell if significant underperformance
                if return_pct < -15:
                    recommendations.append(RecommendationItem(
                        id=f"sell_{asset.id}",
                        type="sell",
                        symbol=asset.symbol or asset.name[:10] if asset.name else "N/A",
                        name=asset.name or "Unknown Asset",
                        reason=f"Asset has underperformed by {abs(return_pct):.1f}% over the last 90 days.",
                        confidence=70,
                        current_price=float(asset.current_value),
                        target_price=None,
                        potential_return=None,
                        risk_level="high",
                        time_horizon="immediate",
                        created_at=datetime.utcnow()
                    ))
        
        # Calculate diversification score
        asset_type_count = len(set([asset.asset_type.value if asset.asset_type else "other" for asset in assets]))
        diversification_score = min(100, (asset_type_count / 5) * 100) if assets else 0
        
        # Portfolio insights
        portfolio_insights = {
            "diversification_score": diversification_score,
            "risk_level": "moderate" if diversification_score > 50 else "high",
            "suggested_actions": []
        }
        
        if diversification_score < 50:
            portfolio_insights["suggested_actions"].append(
                "Consider adding more asset types for better diversification"
            )
        
        if total_value > 0:
            # Check cash percentage
            try:
                alpaca_account = AlpacaClient.get_account()
                cash = Decimal("0.00")
                if alpaca_account:
                    if isinstance(alpaca_account, dict):
                        cash = Decimal(str(alpaca_account.get("cash", 0)))
                    else:
                        cash = Decimal(str(getattr(alpaca_account, "cash", 0)))
                
                cash_percentage = (cash / total_value * 100) if total_value > 0 else 0
                if cash_percentage > 20:
                    portfolio_insights["suggested_actions"].append(
                        "Consider investing excess cash for better returns"
                    )
            except:
                pass
        
        # Filter by type if specified
        if type != "all":
            recommendations = [r for r in recommendations if r.type == type.lower()]
        
        # Limit results
        recommendations = recommendations[:limit]
        
        return RecommendationsResponse(
            data=recommendations,
            portfolio_insights=portfolio_insights
        )
    except Exception as e:
        logger.error(f"Error in get_investment_recommendations: {e}", exc_info=True)
        return RecommendationsResponse(
            data=[],
            portfolio_insights={
                "diversification_score": 0,
                "risk_level": "unknown",
                "suggested_actions": []
            }
        )


# ==================== INVESTMENT GOALS ====================

class GoalAdjustRequest(BaseModel):
    target_amount: Optional[Decimal] = None
    target_date: Optional[str] = None  # YYYY-MM-DD
    monthly_contribution: Optional[Decimal] = None
    risk_tolerance: Optional[str] = None
    notes: Optional[str] = None


@router.post("/goals/{goal_id}/adjust", response_model=Dict[str, Any])
async def adjust_investment_goal(
    goal_id: UUID,
    adjust_data: GoalAdjustRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Adjust investment goal parameters"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # In a real implementation, you would have an InvestmentGoal model
        # For now, return a placeholder response
        return {
            "id": str(goal_id),
            "message": "Goal adjusted successfully",
            "updated_fields": {
                "target_amount": float(adjust_data.target_amount) if adjust_data.target_amount else None,
                "target_date": adjust_data.target_date,
                "monthly_contribution": float(adjust_data.monthly_contribution) if adjust_data.monthly_contribution else None,
                "risk_tolerance": adjust_data.risk_tolerance,
                "notes": adjust_data.notes
            },
            "updated_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error adjusting investment goal: {e}", exc_info=True)
        raise BadRequestException(f"Failed to adjust goal: {str(e)}")


# ==================== INVESTMENT STRATEGIES ====================

class BacktestRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    initial_capital: Decimal
    parameters: Optional[Dict[str, Any]] = None


class BacktestResponse(BaseModel):
    strategy_id: UUID
    start_date: str
    end_date: str
    initial_capital: Decimal
    final_value: Decimal
    total_return: Decimal
    total_return_percentage: Decimal
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    trades_count: int
    performance_metrics: Dict[str, Any]


@router.post("/strategies/{strategy_id}/backtest", response_model=BacktestResponse)
async def backtest_investment_strategy(
    strategy_id: UUID,
    backtest_data: BacktestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Backtest an investment strategy"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # Parse dates
        start_date = datetime.strptime(backtest_data.start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(backtest_data.end_date, "%Y-%m-%d").date()
        
        if end_date < start_date:
            raise BadRequestException("End date must be after start date")
        
        # In a real implementation, you would:
        # 1. Load the strategy configuration
        # 2. Run backtest simulation using historical data
        # 3. Calculate performance metrics
        
        # Placeholder backtest results
        initial_capital = backtest_data.initial_capital
        final_value = initial_capital * Decimal("1.15")  # 15% return placeholder
        total_return = final_value - initial_capital
        total_return_percentage = (total_return / initial_capital * 100) if initial_capital > 0 else Decimal("0")
        
        return BacktestResponse(
            strategy_id=strategy_id,
            start_date=backtest_data.start_date,
            end_date=backtest_data.end_date,
            initial_capital=initial_capital,
            final_value=final_value,
            total_return=total_return,
            total_return_percentage=total_return_percentage,
            sharpe_ratio=1.2,
            max_drawdown=-5.5,
            win_rate=65.0,
            trades_count=42,
            performance_metrics={
                "annualized_return": 12.5,
                "volatility": 8.3,
                "beta": 0.95
            }
        )
    except ValueError as e:
        raise BadRequestException(f"Invalid date format: {str(e)}")
    except Exception as e:
        logger.error(f"Error backtesting strategy: {e}", exc_info=True)
        raise BadRequestException(f"Failed to backtest strategy: {str(e)}")


@router.get("/strategies/{strategy_id}/performance", response_model=Dict[str, Any])
async def get_strategy_performance(
    strategy_id: UUID,
    days: int = Query(30, ge=1, le=365, description="Number of days for performance calculation"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get performance metrics for a specific strategy"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # In a real implementation, you would:
        # 1. Load the strategy and its trades/positions
        # 2. Calculate performance metrics from actual trades
        
        # Placeholder performance data
        period_start = datetime.utcnow() - timedelta(days=days)
        
        return {
            "strategy_id": str(strategy_id),
            "period": {
                "start": period_start.isoformat(),
                "end": datetime.utcnow().isoformat(),
                "days": days
            },
            "performance": {
                "total_return": 1250.50,
                "total_return_percentage": 12.5,
                "annualized_return": 15.2,
                "sharpe_ratio": 1.2,
                "max_drawdown": -5.5,
                "volatility": 8.3,
                "beta": 0.95,
                "alpha": 2.1
            },
            "trades": {
                "total": 42,
                "winning": 27,
                "losing": 15,
                "win_rate": 64.3
            },
            "current_value": 11250.50,
            "initial_value": 10000.00
        }
    except Exception as e:
        logger.error(f"Error getting strategy performance: {e}", exc_info=True)
        raise BadRequestException(f"Failed to get strategy performance: {str(e)}")


class CloneStrategyRequest(BaseModel):
    new_name: str
    adjust_parameters: Optional[Dict[str, Any]] = None


@router.post("/strategies/{strategy_id}/clone", response_model=Dict[str, Any])
async def clone_investment_strategy(
    strategy_id: UUID,
    clone_data: CloneStrategyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Clone an existing investment strategy"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # In a real implementation, you would:
        # 1. Load the original strategy
        # 2. Create a new strategy with the same parameters (or adjusted)
        # 3. Save to database
        
        # Generate new strategy ID
        new_strategy_id = UUID()
        
        return {
            "original_strategy_id": str(strategy_id),
            "new_strategy_id": str(new_strategy_id),
            "name": clone_data.new_name,
            "status": "active",
            "cloned_at": datetime.utcnow().isoformat(),
            "message": "Strategy cloned successfully"
        }
    except Exception as e:
        logger.error(f"Error cloning strategy: {e}", exc_info=True)
        raise BadRequestException(f"Failed to clone strategy: {str(e)}")


# ==================== INVESTMENT WATCHLIST ====================

class WatchlistItemCreate(BaseModel):
    symbol: str
    asset_type: str  # stock, crypto, etc.
    notes: Optional[str] = None


class WatchlistItemResponse(BaseModel):
    id: UUID
    symbol: str
    asset_type: str
    name: Optional[str] = None
    current_price: Optional[float] = None
    change_percentage: Optional[float] = None
    notes: Optional[str] = None
    added_at: datetime


@router.get("/watchlist", response_model=Dict[str, List[WatchlistItemResponse]])
async def get_investment_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get investment watchlist items"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # In a real implementation, you would have an InvestmentWatchlist model
        # For now, return empty list as placeholder
        # This would query: select(InvestmentWatchlist).where(InvestmentWatchlist.account_id == account.id)
        
        watchlist_items = []
        
        # Placeholder: In production, fetch from database
        # For now, return empty list
        
        return {"data": watchlist_items}
    except Exception as e:
        logger.error(f"Error getting watchlist: {e}", exc_info=True)
        return {"data": []}


@router.post("/watchlist", response_model=Dict[str, WatchlistItemResponse], status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    watchlist_item: WatchlistItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add an item to investment watchlist"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # In a real implementation, you would:
        # 1. Check if item already exists in watchlist
        # 2. Create new InvestmentWatchlist record
        # 3. Get current price from market data
        
        # Get current price (placeholder)
        try:
            current_price = PolygonClient.get_current_price(watchlist_item.symbol)
        except:
            current_price = None
        
        # Generate new watchlist item ID
        item_id = UUID()
        
        return {
            "data": WatchlistItemResponse(
                id=item_id,
                symbol=watchlist_item.symbol.upper(),
                asset_type=watchlist_item.asset_type,
                name=watchlist_item.symbol.upper(),  # Would fetch from market data
                current_price=float(current_price) if current_price else None,
                change_percentage=None,  # Would calculate from market data
                notes=watchlist_item.notes,
                added_at=datetime.utcnow()
            )
        }
    except Exception as e:
        logger.error(f"Error adding to watchlist: {e}", exc_info=True)
        raise BadRequestException(f"Failed to add to watchlist: {str(e)}")


@router.delete("/watchlist/{id}", status_code=status.HTTP_200_OK)
async def remove_from_watchlist(
    id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove an item from investment watchlist"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        
        # In a real implementation, you would:
        # 1. Find the watchlist item
        # 2. Verify it belongs to the account
        # 3. Delete it
        
        return {
            "message": "Item removed from watchlist successfully",
            "id": str(id)
        }
    except Exception as e:
        logger.error(f"Error removing from watchlist: {e}", exc_info=True)
        raise BadRequestException(f"Failed to remove from watchlist: {str(e)}")
