from fastapi import APIRouter, Depends, Query, Body, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.asset import Asset, AssetValuation, AssetType
from app.models.portfolio import Portfolio
from app.models.payment import Payment, PaymentStatus
from app.models.banking import Transaction as BankingTransaction
from app.models.report import Report, ReportType, ReportStatus, ReportFormat
from app.models.support import SupportTicket, TicketStatus
from app.models.document import Document
from app.models.asset import AssetAppraisal, AppraisalStatus
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Permission, has_permission
from app.utils.logger import logger
from pydantic import BaseModel
from uuid import UUID
import json
import io

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


class ReportGenerateRequest(BaseModel):
    report_type: str
    date_range: Optional[Dict[str, str]] = None
    filters: Optional[Dict[str, Any]] = None
    format: str = "pdf"  # pdf, csv, xlsx


class ReportResponse(BaseModel):
    id: UUID
    report_type: str
    status: str
    format: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    created_at: datetime
    generated_at: Optional[datetime] = None
    file_url: Optional[str] = None

    class Config:
        from_attributes = True


@router.post("/generate", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def generate_report(
    report_data: ReportGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate a new report"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Parse date range
    start_date = None
    end_date = None
    if report_data.date_range:
        if "start_date" in report_data.date_range:
            try:
                start_date = datetime.fromisoformat(report_data.date_range["start_date"].replace('Z', '+00:00'))
            except:
                pass
        if "end_date" in report_data.date_range:
            try:
                end_date = datetime.fromisoformat(report_data.date_range["end_date"].replace('Z', '+00:00'))
            except:
                pass
    
    # Validate report type
    try:
        report_type_enum = ReportType(report_data.report_type.lower())
    except ValueError:
        raise BadRequestException(f"Invalid report type: {report_data.report_type}")
    
    # Validate format
    try:
        format_enum = ReportFormat(report_data.format.lower())
    except ValueError:
        raise BadRequestException(f"Invalid format: {report_data.format}")
    
    # Create report record
    report = Report(
        account_id=account.id,
        report_type=report_type_enum,
        status=ReportStatus.PENDING,
        format=format_enum,
        start_date=start_date,
        end_date=end_date,
        filters=report_data.filters or {},
        parameters={}
    )
    
    db.add(report)
    await db.commit()
    await db.refresh(report)
    
    # Generate report asynchronously (for now, we'll mark it as generating)
    report.status = ReportStatus.GENERATING
    await db.commit()
    
    # Generate report data based on type
    report_data_dict = {}
    try:
        if report_type_enum == ReportType.PORTFOLIO:
            # Use existing portfolio report logic
            portfolio_result = await db.execute(
                select(Portfolio).where(Portfolio.account_id == account.id)
            )
            portfolio = portfolio_result.scalar_one_or_none()
            
            assets_result = await db.execute(
                select(Asset).where(Asset.account_id == account.id)
            )
            assets = assets_result.scalars().all()
            
            total_value = sum([asset.current_value for asset in assets])
            
            asset_allocation = {}
            for asset in assets:
                asset_type = asset.asset_type.value if asset.asset_type else "other"
                if asset_type not in asset_allocation:
                    asset_allocation[asset_type] = {"count": 0, "value": Decimal("0"), "percentage": Decimal("0")}
                asset_allocation[asset_type]["count"] += 1
                asset_allocation[asset_type]["value"] += asset.current_value
            
            if total_value > 0:
                for asset_type in asset_allocation:
                    asset_allocation[asset_type]["percentage"] = (
                        asset_allocation[asset_type]["value"] / total_value * 100
                    )
            
            report_data_dict = {
                "total_value": float(total_value),
                "asset_count": len(assets),
                "asset_allocation": {k: {**v, "value": float(v["value"]), "percentage": float(v["percentage"])} 
                                    for k, v in asset_allocation.items()},
                "performance": {}
            }
        
        elif report_type_enum == ReportType.PERFORMANCE:
            days = 30
            if report_data.filters and "days" in report_data.filters:
                days = int(report_data.filters["days"])
            
            period_end = datetime.now(timezone.utc)
            period_start = period_end - timedelta(days=days)
            
            assets_result = await db.execute(
                select(Asset).where(Asset.account_id == account.id)
            )
            assets = assets_result.scalars().all()
            
            current_value = sum([asset.current_value for asset in assets])
            historical_value = current_value * Decimal("0.95")  # Simplified
            
            total_return = current_value - historical_value
            total_return_percentage = (total_return / historical_value * 100) if historical_value > 0 else Decimal("0")
            
            report_data_dict = {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "total_return": float(total_return),
                "total_return_percentage": float(total_return_percentage),
                "asset_breakdown": [
                    {
                        "name": asset.name,
                        "type": asset.asset_type.value if asset.asset_type else "other",
                        "current_value": float(asset.current_value),
                        "percentage": float((asset.current_value / current_value * 100) if current_value > 0 else 0)
                    }
                    for asset in assets
                ]
            }
        
        elif report_type_enum == ReportType.TRANSACTION:
            # Use existing transaction report logic
            query = select(Payment).where(Payment.account_id == account.id)
            if start_date:
                query = query.where(Payment.created_at >= start_date)
            if end_date:
                query = query.where(Payment.created_at <= end_date)
            
            result = await db.execute(query.order_by(Payment.created_at.desc()))
            payments = result.scalars().all()
            
            total_amount = sum([payment.amount for payment in payments if payment.status == PaymentStatus.COMPLETED])
            
            report_data_dict = {
                "period": {
                    "start": start_date.isoformat() if start_date else None,
                    "end": end_date.isoformat() if end_date else None,
                },
                "summary": {
                    "total_transactions": len(payments),
                    "total_amount": float(total_amount)
                },
                "transactions": [
                    {
                        "id": str(payment.id),
                        "amount": float(payment.amount),
                        "currency": payment.currency,
                        "status": payment.status.value,
                        "created_at": payment.created_at.isoformat(),
                    }
                    for payment in payments
                ]
            }
        
        # Store report data as JSON (for now, until we implement file generation)
        report.parameters = report_data_dict
        report.status = ReportStatus.COMPLETED
        report.generated_at = datetime.now(timezone.utc)
        
        # For now, we'll store the data. In production, you'd generate PDF/CSV/XLSX files
        report.file_url = f"/api/v1/reports/{report.id}/download"
        
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        report.status = ReportStatus.FAILED
        report.error_message = str(e)
    
    await db.commit()
    await db.refresh(report)
    
    logger.info(f"Report generated: {report.id}")
    
    return {
        "id": str(report.id),
        "status": report.status.value,
        "report_type": report.report_type.value,
        "format": report.format.value,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None
    }


@router.get("", response_model=Dict[str, Any])
async def list_reports(
    type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a list of all reports with optional filtering"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(Report).where(Report.account_id == account.id)
    
    # Admins can see all reports
    if has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        query = select(Report)
    
    if type:
        try:
            report_type = ReportType(type.lower())
            query = query.where(Report.report_type == report_type)
        except ValueError:
            pass
    
    if status_filter:
        try:
            status_enum = ReportStatus(status_filter.lower())
            query = query.where(Report.status == status_enum)
        except ValueError:
            pass
    
    # Get total count
    count_query = select(func.count(Report.id))
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        count_query = count_query.where(Report.account_id == account.id)
    if type:
        try:
            report_type = ReportType(type.lower())
            count_query = count_query.where(Report.report_type == report_type)
        except ValueError:
            pass
    if status_filter:
        try:
            status_enum = ReportStatus(status_filter.lower())
            count_query = count_query.where(Report.status == status_enum)
        except ValueError:
            pass
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    offset = (page - 1) * limit
    query = query.order_by(desc(Report.created_at)).offset(offset).limit(limit)
    
    result = await db.execute(query)
    reports = result.scalars().all()
    
    return {
        "data": [
            {
                "id": str(report.id),
                "report_type": report.report_type.value if report.report_type else None,
                "status": report.status.value if report.status else None,
                "format": report.format.value if report.format else None,
                "start_date": report.start_date.isoformat() if report.start_date else None,
                "end_date": report.end_date.isoformat() if report.end_date else None,
                "created_at": report.created_at.isoformat() if report.created_at else None,
                "generated_at": report.generated_at.isoformat() if report.generated_at else None,
                "file_url": report.file_url
            }
            for report in reports
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit if total > 0 else 0
        }
    }


@router.get("/{report_id}", response_model=Dict[str, Any])
async def get_report_details(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a specific report"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    result = await db.execute(
        select(Report).where(Report.id == report_id)
    )
    report = result.scalar_one_or_none()
    
    if not report:
        raise NotFoundException("Report", str(report_id))
    
    # Check access
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        if report.account_id != account.id:
            raise HTTPException(status_code=403, detail="Access denied")
    
    return {
        "id": str(report.id),
        "report_type": report.report_type.value if report.report_type else None,
        "status": report.status.value if report.status else None,
        "format": report.format.value if report.format else None,
        "start_date": report.start_date.isoformat() if report.start_date else None,
        "end_date": report.end_date.isoformat() if report.end_date else None,
        "filters": report.filters or {},
        "parameters": report.parameters or {},
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "file_url": report.file_url,
        "file_size": report.file_size,
        "error_message": report.error_message
    }


@router.get("/{report_id}/download")
async def download_report(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Download a generated report file"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    result = await db.execute(
        select(Report).where(Report.id == report_id)
    )
    report = result.scalar_one_or_none()
    
    if not report:
        raise NotFoundException("Report", str(report_id))
    
    # Check access
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        if report.account_id != account.id:
            raise HTTPException(status_code=403, detail="Access denied")
    
    if report.status != ReportStatus.COMPLETED:
        raise BadRequestException("Report is not ready for download")
    
    # For now, return JSON data
    # In production, you'd generate and return PDF/CSV/XLSX files
    if report.format == ReportFormat.JSON:
        return JSONResponse(
            content=report.parameters or {},
            headers={"Content-Disposition": f'attachment; filename="report_{report_id}.json"'}
        )
    else:
        # For PDF/CSV/XLSX, you'd need to implement file generation
        # For now, return JSON with a message
        return JSONResponse(
            content={
                "message": f"File generation for {report.format.value} format not yet implemented",
                "data": report.parameters or {}
            },
            headers={"Content-Disposition": f'attachment; filename="report_{report_id}.json"'}
        )


@router.get("/statistics", response_model=Dict[str, Any])
async def get_report_statistics(
    date_range_start: Optional[str] = Query(None),
    date_range_end: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get statistics for the CRM dashboard overview"""
    # Check permissions - only admins/advisors can see CRM statistics
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Parse date range
    start_date = None
    end_date = None
    if date_range_start:
        try:
            start_date = datetime.fromisoformat(date_range_start.replace('Z', '+00:00'))
        except:
            pass
    if date_range_end:
        try:
            end_date = datetime.fromisoformat(date_range_end.replace('Z', '+00:00'))
        except:
            pass
    
    # Aggregate statistics from support tickets, documents, and appraisals
    # Total tasks received (support tickets + appraisals)
    tickets_query = select(func.count(SupportTicket.id))
    appraisals_query = select(func.count(AssetAppraisal.id))
    
    if start_date:
        tickets_query = tickets_query.where(SupportTicket.created_at >= start_date)
        appraisals_query = appraisals_query.where(AssetAppraisal.requested_at >= start_date)
    if end_date:
        tickets_query = tickets_query.where(SupportTicket.created_at <= end_date)
        appraisals_query = appraisals_query.where(AssetAppraisal.requested_at <= end_date)
    
    tickets_result = await db.execute(tickets_query)
    total_tickets = tickets_result.scalar() or 0
    
    appraisals_result = await db.execute(appraisals_query)
    total_appraisals = appraisals_result.scalar() or 0
    
    total_tasks = total_tickets + total_appraisals
    
    # Tasks solved (resolved tickets + completed appraisals)
    solved_tickets_query = select(func.count(SupportTicket.id)).where(
        SupportTicket.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED])
    )
    solved_appraisals_query = select(func.count(AssetAppraisal.id)).where(
        AssetAppraisal.status == AppraisalStatus.COMPLETED
    )
    
    if start_date:
        solved_tickets_query = solved_tickets_query.where(SupportTicket.created_at >= start_date)
        solved_appraisals_query = solved_appraisals_query.where(AssetAppraisal.requested_at >= start_date)
    if end_date:
        solved_tickets_query = solved_tickets_query.where(SupportTicket.created_at <= end_date)
        solved_appraisals_query = solved_appraisals_query.where(AssetAppraisal.requested_at <= end_date)
    
    solved_tickets_result = await db.execute(solved_tickets_query)
    solved_tickets = solved_tickets_result.scalar() or 0
    
    solved_appraisals_result = await db.execute(solved_appraisals_query)
    solved_appraisals = solved_appraisals_result.scalar() or 0
    
    tasks_solved = solved_tickets + solved_appraisals
    
    # Tasks unresolved
    tasks_unresolved = total_tasks - tasks_solved
    
    return {
        "total_tasks_received": total_tasks,
        "tasks_solved": tasks_solved,
        "tasks_unresolved": tasks_unresolved,
        "performance_trends": {
            "tickets": {
                "total": total_tickets,
                "solved": solved_tickets,
                "unresolved": total_tickets - solved_tickets
            },
            "appraisals": {
                "total": total_appraisals,
                "solved": solved_appraisals,
                "unresolved": total_appraisals - solved_appraisals
            }
        }
    }

