from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime, timedelta
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.integrations.alpaca_client import AlpacaClient
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from app.api.deps import get_account, get_user_subscription_plan
from app.core.features import Feature, has_feature
from app.utils.logger import logger
from pydantic import BaseModel

router = APIRouter()


class TransactionResponse(BaseModel):
    id: str
    activity_type: str
    symbol: Optional[str] = None
    quantity: Optional[float] = None
    price: Optional[float] = None
    amount: Optional[float] = None
    date: str
    description: Optional[str] = None


class AssetResponse(BaseModel):
    symbol: str
    qty: float
    market_value: float
    cost_basis: float
    unrealized_pl: float
    unrealized_plpc: float
    current_price: float
    side: str


@router.get("/transactions")
async def get_transactions(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get Alpaca transaction history (read-only, no trading logic)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    try:
        # Default to last 30 days if no dates provided
        if not start_date:
            start_date = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.utcnow().strftime("%Y-%m-%d")
        
        transactions = AlpacaClient.get_transactions(
            start_date=start_date,
            end_date=end_date,
            limit=limit
        )
        
        if transactions is None:
            raise BadRequestException("Failed to fetch transactions. Please check Alpaca configuration.")
        
        # Format transactions for response
        formatted_transactions = []
        for tx in transactions:
            formatted_transactions.append({
                "id": tx.get("id", ""),
                "activity_type": tx.get("activity_type", ""),
                "symbol": tx.get("symbol"),
                "quantity": tx.get("qty"),
                "price": tx.get("price"),
                "amount": tx.get("net_amount") or tx.get("amount"),
                "date": tx.get("date", ""),
                "description": tx.get("description", "")
            })
        
        return {
            "transactions": formatted_transactions,
            "count": len(formatted_transactions),
            "period": {
                "start_date": start_date,
                "end_date": end_date
            }
        }
    except Exception as e:
        logger.error(f"Failed to get Alpaca transactions: {e}")
        raise BadRequestException(f"Failed to fetch transactions: {str(e)}")


@router.get("/assets")
async def get_assets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get Alpaca assets/positions (read-only, no trading logic)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    try:
        positions = AlpacaClient.get_assets()
        
        if positions is None:
            raise BadRequestException("Failed to fetch assets. Please check Alpaca configuration.")
        
        # Format positions for response
        formatted_assets = []
        total_value = 0.0
        total_cost = 0.0
        
        for pos in positions:
            # Handle both dict and object responses
            if isinstance(pos, dict):
                asset_data = pos
            else:
                asset_data = {
                    "symbol": getattr(pos, "symbol", ""),
                    "qty": float(getattr(pos, "qty", 0)),
                    "market_value": float(getattr(pos, "market_value", 0)),
                    "cost_basis": float(getattr(pos, "cost_basis", 0)),
                    "unrealized_pl": float(getattr(pos, "unrealized_pl", 0)),
                    "unrealized_plpc": float(getattr(pos, "unrealized_plpc", 0)),
                    "current_price": float(getattr(pos, "current_price", 0)),
                    "side": getattr(pos, "side", "long")
                }
            
            formatted_assets.append({
                "symbol": asset_data.get("symbol", ""),
                "quantity": asset_data.get("qty", 0),
                "market_value": asset_data.get("market_value", 0),
                "cost_basis": asset_data.get("cost_basis", 0),
                "unrealized_pl": asset_data.get("unrealized_pl", 0),
                "unrealized_pl_percentage": asset_data.get("unrealized_plpc", 0),
                "current_price": asset_data.get("current_price", 0),
                "side": asset_data.get("side", "long")
            })
            
            total_value += asset_data.get("market_value", 0)
            total_cost += asset_data.get("cost_basis", 0)
        
        return {
            "assets": formatted_assets,
            "count": len(formatted_assets),
            "summary": {
                "total_market_value": total_value,
                "total_cost_basis": total_cost,
                "total_unrealized_pl": total_value - total_cost,
                "total_unrealized_pl_percentage": ((total_value - total_cost) / total_cost * 100) if total_cost > 0 else 0
            }
        }
    except Exception as e:
        logger.error(f"Failed to get Alpaca assets: {e}")
        raise BadRequestException(f"Failed to fetch assets: {str(e)}")


@router.get("/account")
async def get_alpaca_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get Alpaca account information (read-only)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    try:
        alpaca_account = AlpacaClient.get_account()
        
        if alpaca_account is None:
            raise BadRequestException("Failed to fetch account. Please check Alpaca configuration.")
        
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
            "account_number": account_data.get("account_number", ""),
            "buying_power": account_data.get("buying_power", 0),
            "cash": account_data.get("cash", 0),
            "portfolio_value": account_data.get("portfolio_value", 0),
            "pattern_day_trader": account_data.get("pattern_day_trader", False),
            "trading_blocked": account_data.get("trading_blocked", False),
            "account_blocked": account_data.get("account_blocked", False),
            "status": account_data.get("status", "")
        }
    except Exception as e:
        logger.error(f"Failed to get Alpaca account: {e}")
        raise BadRequestException(f"Failed to fetch account: {str(e)}")

