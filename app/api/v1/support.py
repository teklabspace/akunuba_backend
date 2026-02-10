from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.support import SupportTicket, TicketStatus, TicketPriority
from app.models.ticket_reply import TicketReply
from app.models.document import Document, DocumentType
from app.integrations.supabase_client import SupabaseClient
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Role, Permission, has_permission
from app.utils.logger import logger
from app.config import settings
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


class TicketAssignRequest(BaseModel):
    user_id: UUID
    user_name: Optional[str] = None
    internal_note: Optional[str] = None


@router.post("/tickets/{ticket_id}/assign", response_model=Dict[str, Any])
async def assign_ticket(
    ticket_id: UUID,
    assign_data: TicketAssignRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Assign a ticket to a CRM user or team"""
    # Check permissions
    if not has_permission(current_user.role, Permission.MANAGE_SUPPORT):
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    
    if not ticket:
        raise NotFoundException("Ticket", str(ticket_id))
    
    # Verify user exists
    user_result = await db.execute(
        select(User).where(User.id == assign_data.user_id)
    )
    user = user_result.scalar_one_or_none()
    
    if not user:
        raise NotFoundException("User", str(assign_data.user_id))
    
    # Assign ticket
    ticket.assigned_to = assign_data.user_id
    
    # Add internal note if provided
    if assign_data.internal_note:
        reply = TicketReply(
            ticket_id=ticket_id,
            user_id=current_user.id,
            message=f"[ASSIGNMENT] {assign_data.internal_note}",
            is_internal="true"
        )
        db.add(reply)
    
    await db.commit()
    await db.refresh(ticket)
    
    logger.info(f"Ticket assigned: {ticket_id} -> {assign_data.user_id}")
    
    return {
        "message": "Ticket assigned successfully",
        "ticket_id": str(ticket_id),
        "assigned_to": str(assign_data.user_id),
        "user_name": assign_data.user_name or user.email
    }


@router.post("/tickets/{ticket_id}/documents", response_model=Dict[str, Any])
async def upload_ticket_documents(
    ticket_id: UUID,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload documents related to a support ticket"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
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
    
    uploaded_documents = []
    
    for file in files:
        # Validate file type
        file_extension = file.filename.split(".")[-1].lower() if "." in file.filename else ""
        if file_extension not in settings.ALLOWED_FILE_TYPES:
            continue
        
        # Read file
        file_data = await file.read()
        file_size = len(file_data)
        
        # Check file size
        if file_size > settings.MAX_UPLOAD_SIZE:
            continue
        
        # Upload to Supabase Storage
        try:
            file_path = f"tickets/{ticket_id}/{file.filename}"
            SupabaseClient.upload_file(
                bucket="documents",
                file_path=file_path,
                file_data=file_data,
                content_type=file.content_type or "application/octet-stream"
            )
        except Exception as e:
            logger.error(f"Failed to upload document: {e}")
            continue
        
        # Create document record linked to ticket
        document = Document(
            account_id=account.id,
            document_type=DocumentType.OTHER,
            file_name=file.filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=file.content_type,
            supabase_storage_path=file_path,
            description=f"Ticket document for ticket {ticket_id}",
            meta_data=f'{{"ticket_id": "{ticket_id}"}}'
        )
        
        db.add(document)
        uploaded_documents.append({
            "id": str(document.id),
            "file_name": file.filename,
            "file_size": file_size
        })
    
    await db.commit()
    
    logger.info(f"Documents uploaded for ticket {ticket_id}: {len(uploaded_documents)} files")
    
    return {
        "message": f"Uploaded {len(uploaded_documents)} document(s)",
        "documents": uploaded_documents
    }


@router.get("/tickets/{ticket_id}/documents", response_model=Dict[str, Any])
async def get_ticket_documents(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all documents associated with a ticket"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
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
    
    # Find documents linked to this ticket via metadata
    documents_result = await db.execute(
        select(Document).where(
            Document.meta_data.contains(f'"ticket_id": "{ticket_id}"')
        )
    )
    documents = documents_result.scalars().all()
    
    document_list = []
    for doc in documents:
        document_list.append({
            "id": str(doc.id),
            "file_name": doc.file_name,
            "file_size": doc.file_size,
            "mime_type": doc.mime_type,
            "created_at": doc.created_at.isoformat() if doc.created_at else None
        })
    
    return {
        "data": document_list,
        "count": len(document_list)
    }


@router.get("/tickets/{ticket_id}/history", response_model=Dict[str, Any])
async def get_ticket_history(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the complete history/activity log for a ticket"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
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
    
    # Build history from ticket fields and replies
    history = []
    
    # Ticket creation
    history.append({
        "type": "created",
        "timestamp": ticket.created_at.isoformat() if ticket.created_at else None,
        "description": "Ticket created",
        "user_id": None
    })
    
    # Status changes (inferred from current status and resolved_at)
    if ticket.resolved_at:
        history.append({
            "type": "status_change",
            "timestamp": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
            "description": f"Status changed to {ticket.status.value}",
            "user_id": None
        })
    
    # Assignment
    if ticket.assigned_to:
        assigned_user_result = await db.execute(
            select(User).where(User.id == ticket.assigned_to)
        )
        assigned_user = assigned_user_result.scalar_one_or_none()
        history.append({
            "type": "assigned",
            "timestamp": ticket.updated_at.isoformat() if ticket.updated_at else None,
            "description": f"Assigned to {assigned_user.email if assigned_user else 'Unknown'}",
            "user_id": str(ticket.assigned_to) if ticket.assigned_to else None
        })
    
    # Replies/comments
    replies_result = await db.execute(
        select(TicketReply).where(TicketReply.ticket_id == ticket_id).order_by(TicketReply.created_at)
    )
    replies = replies_result.scalars().all()
    
    for reply in replies:
        history.append({
            "type": "comment" if not reply.is_internal == "true" else "internal_note",
            "timestamp": reply.created_at.isoformat() if reply.created_at else None,
            "description": reply.message,
            "user_id": str(reply.user_id) if reply.user_id else None
        })
    
    # Sort by timestamp
    history.sort(key=lambda x: x["timestamp"] or "")
    
    return {
        "data": history,
        "count": len(history)
    }

