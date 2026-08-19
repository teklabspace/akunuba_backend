from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, File, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import selectinload, aliased
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.support import SupportTicket, TicketStatus, TicketPriority
from app.models.ticket_reply import TicketReply
from app.models.document import Document, DocumentType
from app.integrations.supabase_client import SupabaseClient
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Permission, has_permission
from app.services.ticket_scope import ticket_scope_for_role
from app.services.ticket_aggregation import count_documents_by_ticket
from app.utils.logger import logger
from app.config import settings
from uuid import UUID
from pydantic import BaseModel, Field

router = APIRouter()


def _ticket_code(n: Optional[int]) -> Optional[str]:
    """Format the sequential ticket number for display, e.g. 1042 -> 'TCK-1042'."""
    return f"TCK-{n:04d}" if n else None


def _display_name(user: Optional[User]) -> str:
    """Best available human name for a user, robust to NULL name parts."""
    if not user:
        return "User"
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return name or (user.email or "User")


def _ticket_dict(
    ticket: SupportTicket,
    requester: Optional[User],
    assignee: Optional[User] = None,
    documents_count: int = 0,
    replies_count: int = 0,
) -> dict:
    """Full ticket row: every column the UI needs, none behind a second call."""
    return {
        "id": ticket.id,
        "ticket_number": _ticket_code(ticket.ticket_number),
        "subject": ticket.subject,
        "description": ticket.description,
        "status": ticket.status.value,
        "priority": ticket.priority.value,
        "category": ticket.category,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at or ticket.created_at,
        "resolved_at": ticket.resolved_at,
        "requester": {
            "id": requester.id if requester else None,
            "name": _display_name(requester),
            "email": requester.email if requester else None,
            "avatar_url": requester.avatar_url if requester else None,
        },
        "assignee": (
            {
                "id": assignee.id,
                "name": _display_name(assignee),
                "avatar_url": assignee.avatar_url,
            }
            if assignee else None
        ),
        "satisfaction_rating": ticket.satisfaction_rating,
        "documents_count": documents_count,
        "replies_count": replies_count,
    }


class TicketCreate(BaseModel):
    subject: str
    description: str
    priority: TicketPriority = TicketPriority.MEDIUM
    category: Optional[str] = None


class TicketRequester(BaseModel):
    id: Optional[UUID] = None
    name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None


class TicketAssignee(BaseModel):
    id: UUID
    name: str
    avatar_url: Optional[str] = None


class TicketResponse(BaseModel):
    id: UUID
    ticket_number: Optional[str] = None
    subject: str
    description: str
    status: str
    priority: str
    category: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    requester: Optional[TicketRequester] = None
    assignee: Optional[TicketAssignee] = None
    satisfaction_rating: Optional[int] = None
    documents_count: int = 0
    replies_count: int = 0

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

    # Notify admins of the new ticket
    try:
        from app.services.notification_service import NotificationService
        from app.models.notification import NotificationType
        await NotificationService.notify_admins(
            db=db,
            notification_type=NotificationType.GENERAL,
            title="New Support Ticket",
            message=f"New ticket: {ticket.subject}",
            metadata=f'{{"ticket_id": "{ticket.id}", "event": "ticket_created"}}',
        )
    except Exception as e:
        logger.error(f"Failed to notify admins of new ticket {ticket.id}: {e}")

    assignee = None
    if ticket.assigned_to:
        assignee = (await db.execute(
            select(User).where(User.id == ticket.assigned_to)
        )).scalar_one_or_none()

    return _ticket_dict(ticket, current_user, assignee)


async def _bulk_reply_documents_counts(
    db: AsyncSession, ticket_ids: List[UUID], is_staff: bool
) -> tuple[Dict[UUID, int], Dict[UUID, int]]:
    """One round trip each for reply counts and document counts across a page of tickets."""
    if not ticket_ids:
        return {}, {}

    reply_query = select(TicketReply.ticket_id, func.count(TicketReply.id)).where(
        TicketReply.ticket_id.in_(ticket_ids)
    )
    if not is_staff:
        # Investors shouldn't see internal-note activity bump their count.
        reply_query = reply_query.where(TicketReply.is_internal == "false")
    reply_rows = (await db.execute(reply_query.group_by(TicketReply.ticket_id))).all()
    replies_count_map = {tid: cnt for tid, cnt in reply_rows}

    meta_data_values = (await db.execute(
        select(Document.meta_data).where(
            or_(*[Document.meta_data.contains(f'"ticket_id": "{tid}"') for tid in ticket_ids])
        )
    )).scalars().all()
    documents_count_map = count_documents_by_ticket(meta_data_values, ticket_ids)

    return replies_count_map, documents_count_map


@router.get("/tickets/stats")
async def get_support_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get support ticket statistics.

    Declared above the ``/tickets/{ticket_id}`` route so FastAPI matches this
    literal path first -- previously "stats" was parsed as a ticket UUID.
    """
    is_staff = has_permission(current_user.role, Permission.MANAGE_SUPPORT)

    account = None
    if not is_staff:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        if not account:
            raise NotFoundException("Account", str(current_user.id))

    scope_conds = [] if is_staff else [SupportTicket.account_id == account.id]

    # Total tickets
    total_result = await db.execute(
        select(func.count(SupportTicket.id)).where(and_(*scope_conds))
    )
    total_tickets = total_result.scalar() or 0

    # By status
    status_result = await db.execute(
        select(
            SupportTicket.status,
            func.count(SupportTicket.id).label("count")
        ).where(and_(*scope_conds)).group_by(SupportTicket.status)
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
        ).where(and_(*scope_conds)).group_by(SupportTicket.priority)
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


@router.get("/tickets", response_model=List[TicketResponse])
async def list_tickets(
    response: Response,
    status: Optional[TicketStatus] = Query(None, description="Filter by status: open, in_progress, resolved, closed"),
    status_filter: Optional[TicketStatus] = Query(None, description="Alias of `status` (backward compatible)"),
    priority: Optional[TicketPriority] = Query(None, description="Filter by priority: low, medium, high, urgent"),
    search: Optional[str] = Query(None, description="Case-insensitive match on subject or description"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List support tickets, enriched with ticket number + requester identity.

    Scope by role (see app.services.ticket_scope, shared with /support/analytics):
      - admin sees every ticket;
      - advisor sees tickets assigned to them;
      - everyone else (investor) sees only their own tickets.
    `status`/`status_filter`, `priority` and `search` behave identically for every role.
    Paginated with `page`/`limit`; total row count comes back in `X-Total-Count`.
    """
    is_staff = has_permission(current_user.role, Permission.MANAGE_SUPPORT)
    scope = ticket_scope_for_role(current_user.role)

    account = None
    if scope != "all":
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        if not account:
            raise NotFoundException("Account", str(current_user.id))

    Assignee = aliased(User)
    # Join the requester (account -> user) so we can return their name/email.
    query = (
        select(SupportTicket, User, Assignee)
        .join(Account, SupportTicket.account_id == Account.id)
        .join(User, Account.user_id == User.id)
        .outerjoin(Assignee, SupportTicket.assigned_to == Assignee.id)
    )

    if scope == "own":
        query = query.where(SupportTicket.account_id == account.id)
    elif scope == "assigned":
        query = query.where(SupportTicket.assigned_to == current_user.id)

    status_value = status or status_filter
    if status_value:
        query = query.where(SupportTicket.status == status_value)
    if priority:
        query = query.where(SupportTicket.priority == priority)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(
            SupportTicket.subject.ilike(term),
            SupportTicket.description.ilike(term),
        ))

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0
    response.headers["X-Total-Count"] = str(total)

    paged_query = (
        query.order_by(SupportTicket.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = (await db.execute(paged_query)).all()

    ticket_ids = [ticket.id for ticket, _, _ in rows]
    replies_count_map, documents_count_map = await _bulk_reply_documents_counts(
        db, ticket_ids, is_staff
    )

    return [
        _ticket_dict(
            ticket, requester, assignee,
            documents_count=documents_count_map.get(ticket.id, 0),
            replies_count=replies_count_map.get(ticket.id, 0),
        )
        for ticket, requester, assignee in rows
    ]


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a support ticket"""
    is_staff = has_permission(current_user.role, Permission.MANAGE_SUPPORT)

    account = None
    if not is_staff:
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
    if not is_staff:
        if not account or ticket.account_id != account.id:
            raise HTTPException(status_code=403, detail="Access denied")

    # Resolve the requester (owner of the ticket's account) and assignee for display.
    requester = (await db.execute(
        select(User).join(Account, Account.user_id == User.id)
        .where(Account.id == ticket.account_id)
    )).scalar_one_or_none()

    assignee = None
    if ticket.assigned_to:
        assignee = (await db.execute(
            select(User).where(User.id == ticket.assigned_to)
        )).scalar_one_or_none()

    replies_count_map, documents_count_map = await _bulk_reply_documents_counts(
        db, [ticket.id], is_staff
    )

    return _ticket_dict(
        ticket, requester, assignee,
        documents_count=documents_count_map.get(ticket.id, 0),
        replies_count=replies_count_map.get(ticket.id, 0),
    )


class TicketUpdateRequest(BaseModel):
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    assigned_to: Optional[UUID] = None


@router.put("/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: UUID,
    update_data: TicketUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a support ticket.

    Accepts a JSON body, e.g. ``{"priority": "high"}`` to escalate,
    ``{"status": "resolved"}`` to close out, or ``{"assigned_to": "<uuid>"}``.
    """
    status = update_data.status
    priority = update_data.priority
    assigned_to = update_data.assigned_to

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
    user_name: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


def _reply_response(reply: TicketReply, author: Optional[User]) -> TicketReplyResponse:
    return TicketReplyResponse(
        id=reply.id,
        message=reply.message,
        is_internal=reply.is_internal == "true",
        user_id=reply.user_id,
        user_name=_display_name(author) if author else None,
        avatar_url=author.avatar_url if author else None,
        created_at=reply.created_at,
    )


@router.post("/tickets/{ticket_id}/replies", response_model=TicketReplyResponse, status_code=status.HTTP_201_CREATED)
@router.post("/tickets/{ticket_id}/comments", response_model=TicketReplyResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
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

    # REAL-TIME: push the reply to the other party so their open thread
    # refreshes instantly (internal notes stay staff-only, so no push).
    if not reply_data.is_internal:
        try:
            import json as _json
            from app.services.notification_service import NotificationService
            from app.models.notification import NotificationType
            meta = _json.dumps({
                "type": "ticket_reply",
                "ticket_id": str(ticket_id),
                "preview": (reply_data.message or "")[:120],
                "author_name": f"{current_user.first_name or ''} {current_user.last_name or ''}".strip(),
            })
            is_staff = has_permission(current_user.role, Permission.MANAGE_SUPPORT)
            if is_staff:
                # Staff replied → notify the ticket owner (bell + WS, no email spam).
                await NotificationService.create_notification(
                    db=db, account_id=ticket.account_id,
                    notification_type=NotificationType.GENERAL,
                    title="Support replied to your ticket",
                    message=(reply_data.message or "")[:200],
                    metadata=meta, send_email=False,
                )
            else:
                # User replied → notify staff (admins) watching the queue.
                await NotificationService.notify_admins(
                    db=db, notification_type=NotificationType.GENERAL,
                    title="New reply on a support ticket",
                    message=(reply_data.message or "")[:200],
                    metadata=meta,
                )
        except Exception as e:
            logger.error(f"Failed to push ticket reply notification: {e}")

    return _reply_response(reply, current_user)


@router.get("/tickets/{ticket_id}/replies", response_model=List[TicketReplyResponse])
@router.get("/tickets/{ticket_id}/comments", response_model=List[TicketReplyResponse], include_in_schema=False)
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
    
    # Eager-load authors so each reply can carry name + avatar (async lazy
    # loading would raise MissingGreenlet).
    query = (
        select(TicketReply)
        .options(selectinload(TicketReply.user))
        .where(TicketReply.ticket_id == ticket_id)
    )

    # Filter internal notes for non-admins
    if not is_admin or not include_internal:
        query = query.where(TicketReply.is_internal == "false")

    result = await db.execute(query.order_by(TicketReply.created_at.asc()))
    replies = result.scalars().all()

    return [_reply_response(reply, reply.user) for reply in replies]


class TicketRatingRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Satisfaction rating, 1-5")
    comment: Optional[str] = None


@router.post("/tickets/{ticket_id}/rating", response_model=Dict[str, Any])
async def rate_ticket(
    ticket_id: UUID,
    body: TicketRatingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a CSAT rating for a resolved/closed ticket. Owner only.

    Feeds the admin support dashboard's satisfaction_rate metric.
    """
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    if not account:
        raise NotFoundException("Account", str(current_user.id))

    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise NotFoundException("Ticket", str(ticket_id))

    # Only the requester rates their own ticket.
    if ticket.account_id != account.id:
        raise HTTPException(status_code=403, detail="You can only rate your own tickets")

    if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        raise BadRequestException("You can only rate a ticket once it's resolved or closed")

    ticket.satisfaction_rating = body.rating
    ticket.satisfaction_comment = body.comment
    await db.commit()
    await db.refresh(ticket)

    logger.info(f"Ticket {ticket_id} rated {body.rating}/5")
    return {
        "message": "Thanks for your feedback",
        "data": {"ticket_id": str(ticket.id), "rating": ticket.satisfaction_rating},
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
        "user_name": assign_data.user_name or user.email,
        "user_avatar": user.avatar_url
    }


@router.post("/tickets/{ticket_id}/documents", response_model=Dict[str, Any])
async def upload_ticket_documents(
    ticket_id: UUID,
    files: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload documents related to a support ticket"""
    is_staff = has_permission(current_user.role, Permission.MANAGE_SUPPORT)

    result = await db.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundException("Ticket", str(ticket_id))

    # Check access
    if not is_staff:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        if not account or ticket.account_id != account.id:
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
            account_id=ticket.account_id,
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
    is_admin = has_permission(current_user.role, Permission.MANAGE_SUPPORT)

    result = await db.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundException("Ticket", str(ticket_id))

    # Check access
    if not is_admin:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        if not account or ticket.account_id != account.id:
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
    is_admin = has_permission(current_user.role, Permission.MANAGE_SUPPORT)

    result = await db.execute(
        select(SupportTicket).where(SupportTicket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if not ticket:
        raise NotFoundException("Ticket", str(ticket_id))

    # Check access
    if not is_admin:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        if not account or ticket.account_id != account.id:
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


def _duration_label(sec: Optional[float]) -> Optional[str]:
    if sec is None:
        return None
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _pct_change(cur, prev):
    if not prev or cur is None:
        return None
    return round((cur - prev) / prev * 100, 1)


@router.get("/analytics", response_model=Dict[str, Any])
async def support_analytics(
    range: str = Query("30d", description="7d | 30d | 90d"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Role-scoped support analytics for the Reports tab.

    Scope is derived from the caller's role so every role gets a meaningful view:
      - admin    -> scope "all"      (every ticket on the platform)
      - advisor  -> scope "assigned" (tickets assigned to this advisor)
      - investor -> scope "own"      (tickets this investor opened)

    Metrics are computed over the selected window (by ticket ``created_at``), with a
    period-over-period ``change_pct`` versus the immediately preceding window.
    For staff scopes ``satisfaction_rate`` reflects CSAT *received*; for the investor
    scope it reflects CSAT *they submitted*.
    """
    # Scope is shared with GET /support/tickets so the two can't disagree.
    scope = ticket_scope_for_role(current_user.role)

    if scope == "all":
        base = []
    elif scope == "assigned":
        base = [SupportTicket.assigned_to == current_user.id]
    else:
        account = (await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )).scalar_one_or_none()
        if not account:
            raise NotFoundException("Account", str(current_user.id))
        base = [SupportTicket.account_id == account.id]

    days = {"7d": 7, "30d": 30, "90d": 90}.get((range or "30d").lower(), 30)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    async def _count(*conds) -> int:
        return (await db.execute(
            select(func.count(SupportTicket.id)).where(and_(*base, *conds))
        )).scalar() or 0

    # Volume (current vs previous window)
    cur_total = await _count(SupportTicket.created_at >= start)
    prev_total = await _count(and_(SupportTicket.created_at >= prev_start,
                                   SupportTicket.created_at < start))

    # Status breakdown within the current window
    status_rows = (await db.execute(
        select(SupportTicket.status, func.count(SupportTicket.id))
        .where(and_(*base, SupportTicket.created_at >= start))
        .group_by(SupportTicket.status)
    )).all()
    by_status = {s.value: 0 for s in TicketStatus}
    for st, cnt in status_rows:
        by_status[st.value] = cnt

    # Unresolved snapshot (open + in_progress), not time-bounded
    unresolved = await _count(SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.IN_PROGRESS]))

    # Avg first-response time (seconds) for tickets first-responded in the window
    async def _avg_first_response(win_start, win_end=None):
        conds = [SupportTicket.first_response_at.isnot(None), SupportTicket.created_at >= win_start]
        if win_end is not None:
            conds.append(SupportTicket.created_at < win_end)
        return (await db.execute(
            select(func.avg(func.extract("epoch", SupportTicket.first_response_at - SupportTicket.created_at)))
            .where(and_(*base, *conds))
        )).scalar()

    avg_fr_cur = await _avg_first_response(start)
    avg_fr_prev = await _avg_first_response(prev_start, start)
    avg_fr_cur_s = int(avg_fr_cur) if avg_fr_cur is not None else None
    avg_fr_prev_s = int(avg_fr_prev) if avg_fr_prev is not None else None

    # Avg resolution time (created -> resolved) for tickets resolved in the window
    async def _avg_resolution(win_start, win_end=None):
        conds = [SupportTicket.resolved_at.isnot(None), SupportTicket.resolved_at >= win_start]
        if win_end is not None:
            conds.append(SupportTicket.resolved_at < win_end)
        return (await db.execute(
            select(func.avg(func.extract("epoch", SupportTicket.resolved_at - SupportTicket.created_at)))
            .where(and_(*base, *conds))
        )).scalar()

    avg_res_cur = await _avg_resolution(start)
    avg_res_prev = await _avg_resolution(prev_start, start)
    avg_res_cur_s = int(avg_res_cur) if avg_res_cur is not None else None
    avg_res_prev_s = int(avg_res_prev) if avg_res_prev is not None else None

    # Satisfaction (avg CSAT rating -> percentage) over rated tickets in the window
    def _rating_pct(avg):
        return round(float(avg) / 5 * 100, 1) if avg is not None else None

    async def _avg_rating(win_start, win_end=None):
        conds = [SupportTicket.satisfaction_rating.isnot(None), SupportTicket.created_at >= win_start]
        if win_end is not None:
            conds.append(SupportTicket.created_at < win_end)
        return (await db.execute(
            select(func.avg(SupportTicket.satisfaction_rating)).where(and_(*base, *conds))
        )).scalar()

    sat_cur = _rating_pct(await _avg_rating(start))
    sat_prev = _rating_pct(await _avg_rating(prev_start, start))

    return {
        "scope": scope,
        "range": f"{days}d",
        "summary": {
            "total_tickets": {"value": cur_total, "change_pct": _pct_change(cur_total, prev_total)},
            "by_status": by_status,
            "unresolved_issues": {"value": unresolved, "change_pct": None},
            "avg_first_response": {
                "value_seconds": avg_fr_cur_s,
                "value_label": _duration_label(avg_fr_cur_s),
                "change_pct": _pct_change(avg_fr_cur_s, avg_fr_prev_s),
            },
            "avg_resolution": {
                "value_seconds": avg_res_cur_s,
                "value_label": _duration_label(avg_res_cur_s),
                "change_pct": _pct_change(avg_res_cur_s, avg_res_prev_s),
            },
            "satisfaction_rate": {
                "value": sat_cur,
                "change_pct": _pct_change(sat_cur, sat_prev),
                "note": None if sat_cur is not None else "No CSAT ratings in this period yet.",
            },
        },
    }

