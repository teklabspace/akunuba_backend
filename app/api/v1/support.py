from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from datetime import datetime
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.support import SupportTicket, TicketStatus, TicketPriority
from app.models.ticket_reply import TicketReply
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Role, Permission, has_permission
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


class TicketCreate(BaseModel):
    subject: str
    description: str
    priority: TicketPriority = TicketPriority.MEDIUM
    category: Optional[str] = None


class TicketResponse(BaseModel):
    id: UUID
    subject: str
    status: str
    priority: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/tickets", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    ticket_data: TicketCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a support ticket"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    from app.services.sla_service import SLAService
    from app.services.ticket_assignment_service import TicketAssignmentService
    
    ticket = SupportTicket(
        account_id=account.id,
        subject=ticket_data.subject,
        description=ticket_data.description,
        priority=ticket_data.priority,
        category=ticket_data.category,
        status=TicketStatus.OPEN,
    )
    
    # Set SLA targets
    await SLAService.set_sla_targets(db, ticket)
    
    # Auto-assign if enabled
    await TicketAssignmentService.auto_assign_ticket(db, ticket)
    
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    
    logger.info(f"Support ticket created: {ticket.id}")
    return ticket


@router.get("/tickets", response_model=List[TicketResponse])
async def list_tickets(
    status_filter: Optional[TicketStatus] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List support tickets"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(SupportTicket).where(SupportTicket.account_id == account.id)
    
    # Admins can see all tickets
    if has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        query = select(SupportTicket)
        if status_filter:
            query = query.where(SupportTicket.status == status_filter)
    elif status_filter:
        query = query.where(SupportTicket.status == status_filter)
    
    result = await db.execute(query.order_by(SupportTicket.created_at.desc()))
    tickets = result.scalars().all()
    
    return tickets


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a support ticket"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    result = await db.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    
    if not ticket:
        raise NotFoundException("Ticket", str(ticket_id))
    
    # Check access
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        if ticket.account_id != account.id:
            raise HTTPException(status_code=403, detail="Access denied")
    
    return ticket


@router.put("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: UUID,
    status: Optional[TicketStatus] = None,
    priority: Optional[TicketPriority] = None,
    assigned_to: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a support ticket"""
    result = await db.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    
    if not ticket:
        raise NotFoundException("Ticket", str(ticket_id))
    
    # Check permissions
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        if ticket.account_id != account.id:
            raise HTTPException(status_code=403, detail="Access denied")
        # Users can only update status to resolved
        if status and status != TicketStatus.RESOLVED:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    if status:
        ticket.status = status
        if status == TicketStatus.RESOLVED:
            ticket.resolved_at = datetime.utcnow()
    
    if priority:
        ticket.priority = priority
    
    if assigned_to and has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        ticket.assigned_to = assigned_to
    
    await db.commit()
    await db.refresh(ticket)
    
    logger.info(f"Ticket updated: {ticket_id}")
    return ticket


class TicketReplyCreate(BaseModel):
    message: str
    is_internal: bool = False


class TicketReplyResponse(BaseModel):
    id: UUID
    message: str
    is_internal: bool
    user_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/tickets/{ticket_id}/replies", response_model=TicketReplyResponse, status_code=status.HTTP_201_CREATED)
async def create_ticket_reply(
    ticket_id: UUID,
    reply_data: TicketReplyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a reply to a support ticket"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    result = await db.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    
    if not ticket:
        raise NotFoundException("Ticket", str(ticket_id))
    
    # Check access
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        if ticket.account_id != account.id:
            raise HTTPException(status_code=403, detail="Access denied")
        # Users can't create internal notes
        if reply_data.is_internal:
            raise HTTPException(status_code=403, detail="Only admins can create internal notes")
    
    # Update ticket status if user replies
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        if ticket.status == TicketStatus.RESOLVED:
            ticket.status = TicketStatus.OPEN
    else:
        # Admin reply - mark as in progress if open
        if ticket.status == TicketStatus.OPEN:
            ticket.status = TicketStatus.IN_PROGRESS
    
    reply = TicketReply(
        ticket_id=ticket_id,
        user_id=current_user.id,
        message=reply_data.message,
        is_internal="true" if reply_data.is_internal else "false"
    )
    
    db.add(reply)
    await db.commit()
    await db.refresh(reply)
    
    logger.info(f"Ticket reply created: {reply.id} for ticket {ticket_id}")
    return reply


@router.get("/tickets/{ticket_id}/replies", response_model=List[TicketReplyResponse])
async def get_ticket_replies(
    ticket_id: UUID,
    include_internal: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get replies for a support ticket"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    result = await db.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    
    if not ticket:
        raise NotFoundException("Ticket", str(ticket_id))
    
    # Check access
    is_admin = has_permission(current_user.role, Permission.MANAGE_SUPPORT)
    if not is_admin:
        if ticket.account_id != account.id:
            raise HTTPException(status_code=403, detail="Access denied")
    
    query = select(TicketReply).where(TicketReply.ticket_id == ticket_id)
    
    # Filter internal notes for non-admins
    if not is_admin or not include_internal:
        query = query.where(TicketReply.is_internal == "false")
    
    result = await db.execute(query.order_by(TicketReply.created_at.asc()))
    replies = result.scalars().all()
    
    return replies


@router.get("/tickets/stats")
async def get_support_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get support ticket statistics"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Base query
    if has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        query = select(SupportTicket)
    else:
        query = select(SupportTicket).where(SupportTicket.account_id == account.id)
    
    # Total tickets
    total_result = await db.execute(
        select(func.count(SupportTicket.id)).select_from(query.subquery())
    )
    total_tickets = total_result.scalar() or 0
    
    # By status
    status_result = await db.execute(
        select(
            SupportTicket.status,
            func.count(SupportTicket.id).label("count")
        ).where(
            SupportTicket.account_id == account.id if not has_permission(current_user.role, Permission.MANAGE_SUPPORT) else True
        ).group_by(SupportTicket.status)
    )
    by_status = {
        row.status.value: row.count
        for row in status_result.all()
    }
    
    # By priority
    priority_result = await db.execute(
        select(
            SupportTicket.priority,
            func.count(SupportTicket.id).label("count")
        ).where(
            SupportTicket.account_id == account.id if not has_permission(current_user.role, Permission.MANAGE_SUPPORT) else True
        ).group_by(SupportTicket.priority)
    )
    by_priority = {
        row.priority.value: row.count
        for row in priority_result.all()
    }
    
    return {
        "total_tickets": total_tickets,
        "by_status": by_status,
        "by_priority": by_priority
    }

