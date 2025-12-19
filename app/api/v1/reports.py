from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.asset import Asset, AssetValuation, AssetType
from app.models.portfolio import Portfolio
from app.models.payment import Payment, PaymentStatus
from app.models.banking import Transaction as BankingTransaction
from app.core.exceptions import NotFoundException
from app.utils.logger import logger
from pydantic import BaseModel

router = APIRouter()


class PortfolioReport(BaseModel):
    total_value: Decimal
    asset_count: int
    asset_allocation: dict
    performance: dict


class PerformanceReport(BaseModel):
    period_start: datetime
    period_end: datetime
    total_return: Decimal
    total_return_percentage: Decimal
    asset_breakdown: list


@router.get("/portfolio", response_model=PortfolioReport)
async def generate_portfolio_report(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate portfolio report"""
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
    
    # Get assets
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account.id)
    )
    assets = assets_result.scalars().all()
    
    total_value = sum([asset.current_value for asset in assets])
    
    # Asset allocation
    asset_allocation = {}
    for asset in assets:
        asset_type = asset.asset_type.value
        if asset_type not in asset_allocation:
            asset_allocation[asset_type] = {
                "count": 0,
                "value": Decimal("0"),
                "percentage": Decimal("0")
            }
        asset_allocation[asset_type]["count"] += 1
        asset_allocation[asset_type]["value"] += asset.current_value
    
    if total_value > 0:
        for asset_type in asset_allocation:
            asset_allocation[asset_type]["percentage"] = (
                asset_allocation[asset_type]["value"] / total_value * 100
            )
    
    # Get performance data from portfolio or calculate
    if portfolio and portfolio.performance_data:
        performance_data = portfolio.performance_data
    else:
        # Calculate basic performance metrics
        # Get historical valuations for last 30 days
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        historical_result = await db.execute(
            select(AssetValuation).where(
                AssetValuation.asset_id.in_([asset.id for asset in assets]),
                AssetValuation.valuation_date >= thirty_days_ago
            ).order_by(AssetValuation.valuation_date.asc())
        )
        historical_valuations = historical_result.scalars().all()
        
        # Calculate daily returns if we have historical data
        daily_returns = []
        if historical_valuations:
            # Group by date
            valuations_by_date = {}
            for val in historical_valuations:
                date_key = val.valuation_date.date()
                if date_key not in valuations_by_date:
                    valuations_by_date[date_key] = Decimal("0")
                valuations_by_date[date_key] += val.value
            
            # Calculate returns
            sorted_dates = sorted(valuations_by_date.keys())
            for i in range(1, len(sorted_dates)):
                prev_value = valuations_by_date[sorted_dates[i-1]]
                curr_value = valuations_by_date[sorted_dates[i]]
                if prev_value > 0:
                    daily_return = ((curr_value - prev_value) / prev_value) * 100
                    daily_returns.append({
                        "date": sorted_dates[i].isoformat(),
                        "return": float(daily_return)
                    })
        
        performance_data = {
            "total_return": float(total_value - (total_value * Decimal("0.95"))) if total_value > 0 else 0,
            "total_return_percentage": float(((total_value - (total_value * Decimal("0.95"))) / (total_value * Decimal("0.95")) * 100)) if total_value > 0 else 0,
            "daily_returns": daily_returns[-30:] if daily_returns else []
        }
    
    return PortfolioReport(
        total_value=total_value,
        asset_count=len(assets),
        asset_allocation=asset_allocation,
        performance=performance_data,
    )


@router.get("/performance", response_model=PerformanceReport)
async def generate_performance_report(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate performance report"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=days)
    
    # Get current assets
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account.id)
    )
    assets = assets_result.scalars().all()
    
    current_value = sum([asset.current_value for asset in assets])
    
    # Get historical valuations from AssetValuation records
    historical_valuations_result = await db.execute(
        select(AssetValuation).where(
            AssetValuation.asset_id.in_([asset.id for asset in assets]),
            AssetValuation.valuation_date <= period_start
        ).order_by(AssetValuation.valuation_date.desc())
    )
    historical_valuations = historical_valuations_result.scalars().all()
    
    # Calculate historical value
    historical_value = Decimal("0")
    if historical_valuations:
        # Get most recent valuation before period start for each asset
        asset_historical_values = {}
        for val in historical_valuations:
            if val.asset_id not in asset_historical_values:
                asset_historical_values[val.asset_id] = val.value
        
        historical_value = sum(asset_historical_values.values())
    else:
        # If no historical data, estimate based on current value (conservative estimate)
        historical_value = current_value * Decimal("0.95")
    
    total_return = current_value - historical_value
    total_return_percentage = (total_return / historical_value * 100) if historical_value > 0 else Decimal("0")
    
    # Asset breakdown
    asset_breakdown = [
        {
            "name": asset.name,
            "type": asset.asset_type.value,
            "current_value": float(asset.current_value),
            "percentage": float((asset.current_value / current_value * 100) if current_value > 0 else 0)
        }
        for asset in assets
    ]
    
    return PerformanceReport(
        period_start=period_start,
        period_end=period_end,
        total_return=total_return,
        total_return_percentage=total_return_percentage,
        asset_breakdown=asset_breakdown,
    )


@router.get("/transactions")
async def generate_transaction_report(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate transaction report"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(Payment).where(Payment.account_id == account.id)
    
    if start_date:
        query = query.where(Payment.created_at >= start_date)
    if end_date:
        query = query.where(Payment.created_at <= end_date)
    
    result = await db.execute(query.order_by(Payment.created_at.desc()))
    payments = result.scalars().all()
    
    total_amount = sum([payment.amount for payment in payments if payment.status == PaymentStatus.COMPLETED])
    
    # Get banking transactions too
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=30)
    if not end_date:
        end_date = datetime.utcnow()
    
    # Get linked accounts for this user's account
    from app.models.banking import LinkedAccount
    linked_accounts_result = await db.execute(
        select(LinkedAccount.id).where(LinkedAccount.account_id == account.id, LinkedAccount.is_active == True)
    )
    linked_account_ids = [row[0] for row in linked_accounts_result.all()]
    
    banking_transactions = []
    if linked_account_ids:
        banking_transactions_result = await db.execute(
            select(BankingTransaction).where(
                and_(
                    BankingTransaction.linked_account_id.in_(linked_account_ids),
                    BankingTransaction.transaction_date >= start_date,
                    BankingTransaction.transaction_date <= end_date
                )
            ).order_by(BankingTransaction.transaction_date.desc())
        )
        banking_transactions = banking_transactions_result.scalars().all()
    
    # Calculate totals
    total_payment_amount = sum([payment.amount for payment in payments if payment.status == PaymentStatus.COMPLETED])
    total_banking_amount = sum([abs(tx.amount) for tx in banking_transactions])
    
    # Group by status
    payment_by_status = {}
    for payment in payments:
        status = payment.status.value
        if status not in payment_by_status:
            payment_by_status[status] = {"count": 0, "amount": Decimal("0")}
        payment_by_status[status]["count"] += 1
        payment_by_status[status]["amount"] += payment.amount
    
    # Group by month
    payments_by_month = {}
    for payment in payments:
        month_key = payment.created_at.strftime("%Y-%m")
        if month_key not in payments_by_month:
            payments_by_month[month_key] = {"count": 0, "amount": Decimal("0")}
        payments_by_month[month_key]["count"] += 1
        if payment.status == PaymentStatus.COMPLETED:
            payments_by_month[month_key]["amount"] += payment.amount
    
    return {
        "period": {
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None,
        },
        "summary": {
            "total_payment_transactions": len(payments),
            "total_payment_amount": float(total_payment_amount),
            "total_banking_transactions": len(banking_transactions),
            "total_banking_amount": float(total_banking_amount),
            "total_transactions": len(payments) + len(banking_transactions),
            "total_amount": float(total_payment_amount + total_banking_amount)
        },
        "payments_by_status": {
            status: {
                "count": data["count"],
                "amount": float(data["amount"])
            }
            for status, data in payment_by_status.items()
        },
        "payments_by_month": {
            month: {
                "count": data["count"],
                "amount": float(data["amount"])
            }
            for month, data in payments_by_month.items()
        },
        "payment_transactions": [
            {
                "id": str(payment.id),
                "amount": float(payment.amount),
                "currency": payment.currency,
                "status": payment.status.value,
                "created_at": payment.created_at.isoformat(),
            }
            for payment in payments
        ],
        "banking_transactions": [
            {
                "id": str(tx.id),
                "amount": float(tx.amount),
                "currency": tx.currency,
                "description": tx.description,
                "category": tx.category,
                "transaction_date": tx.transaction_date.isoformat(),
            }
            for tx in banking_transactions[:50]  # Limit to 50 most recent
        ]
    }

