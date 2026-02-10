from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User, Role
from app.models.account import Account
from app.models.support import SupportTicket, TicketStatus
from app.models.document import Document
from app.models.asset import AssetAppraisal, AppraisalStatus
from app.core.exceptions import NotFoundException
from app.core.permissions import Permission, has_permission
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


class CRMUserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/users", response_model=Dict[str, Any])
async def get_crm_users(
    role: Optional[str] = Query(None),
    team: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of CRM users available for assignment"""
    # Check permissions - only admins and advisors can see CRM users
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    query = select(User)
    
    # Filter by role if provided
    if role:
        try:
            role_enum = Role(role.lower())
            query = query.where(User.role == role_enum)
        except ValueError:
            pass
    
    # Note: "team" filtering would require a team model/field
    # For now, we'll filter by role which is the closest equivalent
    
    result = await db.execute(query.order_by(User.created_at.desc()))
    users = result.scalars().all()
    
    user_list = []
    for user in users:
        # Only return users with CRM permissions (admin, advisor)
        if has_permission(user.role, Permission.MANAGE_SUPPORT):
            user_list.append({
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name if hasattr(user, 'full_name') else None,
                "role": user.role.value if user.role else None,
                "created_at": user.created_at.isoformat() if user.created_at else None
            })
    
    return {
        "data": user_list,
        "count": len(user_list)
    }


@router.get("/dashboard/overview", response_model=Dict[str, Any])
async def get_crm_dashboard_overview(
    date_range_start: Optional[str] = Query(None),
    date_range_end: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get overall statistics for the CRM dashboard"""
    # Check permissions
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
    
    # Tasks solved
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
    
    # Performance trends (last 7 days)
    trend_days = 7
    trend_data = []
    for i in range(trend_days):
        day_start = datetime.now(timezone.utc) - timedelta(days=trend_days - i)
        day_end = day_start + timedelta(days=1)
        
        day_tickets = await db.execute(
            select(func.count(SupportTicket.id)).where(
                SupportTicket.created_at >= day_start,
                SupportTicket.created_at < day_end
            )
        )
        day_tickets_count = day_tickets.scalar() or 0
        
        day_appraisals = await db.execute(
            select(func.count(AssetAppraisal.id)).where(
                AssetAppraisal.requested_at >= day_start,
                AssetAppraisal.requested_at < day_end
            )
        )
        day_appraisals_count = day_appraisals.scalar() or 0
        
        trend_data.append({
            "date": day_start.date().isoformat(),
            "tasks_received": day_tickets_count + day_appraisals_count,
            "tickets": day_tickets_count,
            "appraisals": day_appraisals_count
        })
    
    # Recent updates (last 10)
    recent_updates = []
    
    # Recent tickets
    recent_tickets_result = await db.execute(
        select(SupportTicket).order_by(desc(SupportTicket.updated_at)).limit(5)
    )
    recent_tickets = recent_tickets_result.scalars().all()
    
    for ticket in recent_tickets:
        recent_updates.append({
            "type": "ticket",
            "id": str(ticket.id),
            "title": ticket.subject,
            "status": ticket.status.value if ticket.status else None,
            "timestamp": ticket.updated_at.isoformat() if ticket.updated_at else ticket.created_at.isoformat() if ticket.created_at else None
        })
    
    # Recent appraisals
    recent_appraisals_result = await db.execute(
        select(AssetAppraisal).order_by(desc(AssetAppraisal.updated_at)).limit(5)
    )
    recent_appraisals = recent_appraisals_result.scalars().all()
    
    for appraisal in recent_appraisals:
        recent_updates.append({
            "type": "appraisal",
            "id": str(appraisal.id),
            "title": f"Appraisal {appraisal.id}",
            "status": appraisal.status.value if appraisal.status else None,
            "timestamp": appraisal.updated_at.isoformat() if appraisal.updated_at else appraisal.requested_at.isoformat() if appraisal.requested_at else None
        })
    
    # Sort by timestamp and take most recent 10
    recent_updates.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    recent_updates = recent_updates[:10]
    
    return {
        "total_tasks_received": total_tasks,
        "tasks_solved": tasks_solved,
        "tasks_unresolved": tasks_unresolved,
        "performance_trends": trend_data,
        "recent_updates": recent_updates,
        "breakdown": {
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


@router.get("/updates", response_model=Dict[str, Any])
async def get_task_updates(
    type: Optional[str] = Query(None),  # pinned, ticket, task
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get recent updates and activity feed for CRM dashboard"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    updates = []
    
    # Get tickets
    if not type or type == "ticket":
        tickets_result = await db.execute(
            select(SupportTicket).order_by(desc(SupportTicket.updated_at)).limit(limit)
        )
        tickets = tickets_result.scalars().all()
        
        for ticket in tickets:
            updates.append({
                "type": "ticket",
                "id": str(ticket.id),
                "title": ticket.subject,
                "description": ticket.description[:100] if ticket.description else None,
                "status": ticket.status.value if ticket.status else None,
                "priority": ticket.priority.value if ticket.priority else None,
                "timestamp": ticket.updated_at.isoformat() if ticket.updated_at else ticket.created_at.isoformat() if ticket.created_at else None,
                "is_pinned": False  # Would require pinned field
            })
    
    # Get appraisals (as tasks)
    if not type or type == "task":
        appraisals_result = await db.execute(
            select(AssetAppraisal).order_by(desc(AssetAppraisal.updated_at)).limit(limit)
        )
        appraisals = appraisals_result.scalars().all()
        
        for appraisal in appraisals:
            # Get asset name
            asset_name = None
            if appraisal.asset_id:
                asset_result = await db.execute(
                    select(Asset).where(Asset.id == appraisal.asset_id)
                )
                asset = asset_result.scalar_one_or_none()
                if asset:
                    asset_name = asset.name
            
            updates.append({
                "type": "task",
                "id": str(appraisal.id),
                "title": f"Appraisal: {asset_name or 'Unknown Asset'}",
                "description": appraisal.notes[:100] if appraisal.notes else None,
                "status": appraisal.status.value if appraisal.status else None,
                "timestamp": appraisal.updated_at.isoformat() if appraisal.updated_at else appraisal.requested_at.isoformat() if appraisal.requested_at else None,
                "is_pinned": False
            })
    
    # Sort by timestamp
    updates.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    
    # Apply limit
    updates = updates[:limit]
    
    return {
        "data": updates,
        "count": len(updates)
    }
