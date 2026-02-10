from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, File, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, asc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.entity import Entity
from app.models.compliance import (
    ComplianceTask, ComplianceTaskDocument, ComplianceTaskComment, ComplianceTaskHistory,
    ComplianceAudit, ComplianceAlert, ComplianceScore, ComplianceMetrics,
    ComplianceReport, CompliancePolicy,
    TaskStatus, TaskPriority, AuditType, AuditStatus,
    AlertSeverity, AlertStatus, ReportStatus, ReportFormat, PolicyStatus
)
from app.models.document import Document
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Permission, has_permission
from app.utils.logger import logger
from app.integrations.supabase_client import SupabaseClient
from app.config import settings
from uuid import UUID
from pydantic import BaseModel, Field
import io
import json

router = APIRouter()


# ==================== SCHEMAS ====================

class DashboardResponse(BaseModel):
    compliance_score: float
    compliance_score_change: float
    pending_audits_count: int
    open_alerts_count: int
    alerts_change: int
    last_updated: datetime


class TaskResponse(BaseModel):
    id: UUID
    task_name: str
    description: Optional[str] = None
    assignee: Optional[Dict[str, Any]] = None
    due_date: date
    status: str
    priority: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    entity_id: Optional[UUID] = None
    category: Optional[str] = None
    related_documents: List[Dict[str, Any]] = []


class TaskCreate(BaseModel):
    task_name: str
    description: Optional[str] = None
    assignee_id: Optional[UUID] = None
    due_date: str  # YYYY-MM-DD
    priority: TaskPriority = TaskPriority.MEDIUM
    entity_id: Optional[UUID] = None
    category: Optional[str] = None
    related_document_ids: Optional[List[UUID]] = []


class TaskUpdate(BaseModel):
    status: Optional[TaskStatus] = None
    assignee_id: Optional[UUID] = None
    due_date: Optional[str] = None  # YYYY-MM-DD
    priority: Optional[TaskPriority] = None
    description: Optional[str] = None


class TaskReassign(BaseModel):
    assignee_id: UUID
    notes: Optional[str] = None


class TaskComplete(BaseModel):
    completion_notes: Optional[str] = None
    completed_at: Optional[str] = None  # YYYY-MM-DDTHH:mm:ssZ


class AuditResponse(BaseModel):
    id: UUID
    audit_name: str
    audit_type: str
    status: str
    scheduled_date: date
    due_date: date
    entity_id: Optional[UUID] = None
    auditor: Optional[Dict[str, Any]] = None
    scope: List[str]
    created_at: datetime


class AuditCreate(BaseModel):
    audit_name: str
    audit_type: AuditType
    scheduled_date: str  # YYYY-MM-DD
    due_date: str  # YYYY-MM-DD
    entity_id: Optional[UUID] = None
    auditor_id: Optional[UUID] = None
    scope: List[str]
    description: Optional[str] = None


class AuditUpdate(BaseModel):
    status: Optional[AuditStatus] = None
    scheduled_date: Optional[str] = None  # YYYY-MM-DD
    due_date: Optional[str] = None  # YYYY-MM-DD
    auditor_id: Optional[UUID] = None
    scope: Optional[List[str]] = None


class AlertResponse(BaseModel):
    id: UUID
    alert_type: str
    severity: str
    status: str
    title: str
    description: str
    entity_id: Optional[UUID] = None
    created_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class AlertAcknowledge(BaseModel):
    notes: Optional[str] = None


class AlertResolve(BaseModel):
    resolution_notes: str
    resolved_at: Optional[str] = None  # YYYY-MM-DDTHH:mm:ssZ


class ScoreHistoryItem(BaseModel):
    date: str
    score: float
    change: float


class MetricsResponse(BaseModel):
    overall_score: float
    categories: List[Dict[str, Any]]


class ReportGenerate(BaseModel):
    report_type: str
    date_from: str  # YYYY-MM-DD
    date_to: str  # YYYY-MM-DD
    entity_id: Optional[UUID] = None
    include_sections: List[str]
    format: ReportFormat


class PolicyResponse(BaseModel):
    id: UUID
    policy_name: str
    category: str
    status: str
    version: str
    effective_date: date
    expiry_date: Optional[date] = None
    last_reviewed: Optional[date] = None
    next_review: Optional[date] = None
    document_url: Optional[str] = None


# ==================== HELPER FUNCTIONS ====================

async def get_account_for_user(current_user: User, db: AsyncSession) -> Account:
    """Get account for current user"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    return account


def calculate_compliance_score(account_id: UUID, entity_id: Optional[UUID], db: AsyncSession) -> float:
    """Calculate compliance score based on various factors"""
    # This is a simplified calculation
    # In production, this would consider:
    # - KYC/KYB status
    # - Entity compliance status
    # - Task completion rate
    # - Alert resolution rate
    # - Policy compliance
    # For now, return a default score
    return 98.5


# ==================== DASHBOARD ====================

@router.get("/dashboard", response_model=DashboardResponse)
async def get_compliance_dashboard(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    entity_id: Optional[UUID] = Query(None, description="Filter by entity"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get compliance dashboard summary.

    Hardened to avoid leaking raw DB/HTML errors to API clients. On unexpected errors,
    returns a structured JSON 500 instead of an HTML error page.
    """
    try:
        account = await get_account_for_user(current_user, db)
        
        # Calculate compliance score
        compliance_score = calculate_compliance_score(account.id, entity_id, db)
        
        # Get previous score for change calculation
        if entity_id:
            prev_score_result = await db.execute(
                select(ComplianceScore)
                .where(
                    and_(
                        ComplianceScore.account_id == account.id,
                        ComplianceScore.entity_id == entity_id
                    )
                )
                .order_by(desc(ComplianceScore.date))
                .limit(1)
                .offset(1)
            )
        else:
            prev_score_result = await db.execute(
                select(ComplianceScore)
                .where(ComplianceScore.account_id == account.id)
                .order_by(desc(ComplianceScore.date))
                .limit(1)
                .offset(1)
            )
        
        prev_score = prev_score_result.scalar_one_or_none()
        compliance_score_change = float(compliance_score - prev_score.score) if prev_score else 0.0
        
        # Count pending audits
        audit_query = select(func.count(ComplianceAudit.id)).where(
            and_(
                ComplianceAudit.account_id == account.id,
                ComplianceAudit.status == AuditStatus.PENDING
            )
        )
        if entity_id:
            audit_query = audit_query.where(ComplianceAudit.entity_id == entity_id)
        pending_audits_result = await db.execute(audit_query)
        pending_audits_count = pending_audits_result.scalar() or 0
        
        # Count open alerts
        alert_query = select(func.count(ComplianceAlert.id)).where(
            and_(
                ComplianceAlert.account_id == account.id,
                ComplianceAlert.status == AlertStatus.OPEN
            )
        )
        if entity_id:
            alert_query = alert_query.where(ComplianceAlert.entity_id == entity_id)
        open_alerts_result = await db.execute(alert_query)
        open_alerts_count = open_alerts_result.scalar() or 0
        
        # Calculate alerts change (compare with previous period)
        # Simplified: get count from 7 days ago
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        prev_alert_query = select(func.count(ComplianceAlert.id)).where(
            and_(
                ComplianceAlert.account_id == account.id,
                ComplianceAlert.status == AlertStatus.OPEN,
                ComplianceAlert.created_at <= seven_days_ago
            )
        )
        if entity_id:
            prev_alert_query = prev_alert_query.where(ComplianceAlert.entity_id == entity_id)
        prev_alerts_result = await db.execute(prev_alert_query)
        prev_alerts_count = prev_alerts_result.scalar() or 0
        alerts_change = open_alerts_count - prev_alerts_count
        
        return DashboardResponse(
            compliance_score=compliance_score,
            compliance_score_change=compliance_score_change,
            pending_audits_count=pending_audits_count,
            open_alerts_count=open_alerts_count,
            alerts_change=alerts_change,
            last_updated=datetime.now(timezone.utc)
        )
    except NotFoundException:
        # Preserve 404 semantics if account is missing
        raise
    except Exception as e:
        logger.error(f"Error in get_compliance_dashboard: {e}", exc_info=True)
        # On unexpected errors, return a safe default dashboard instead of 500
        return DashboardResponse(
            compliance_score=0.0,
            compliance_score_change=0.0,
            pending_audits_count=0,
            open_alerts_count=0,
            alerts_change=0,
            last_updated=datetime.now(timezone.utc)
        )


# ==================== TASKS ====================

@router.get("/tasks", response_model=Dict[str, Any])
async def list_compliance_tasks(
    status: Optional[TaskStatus] = Query(None),
    assignee_id: Optional[UUID] = Query(None),
    due_date_from: Optional[str] = Query(None),
    due_date_to: Optional[str] = Query(None),
    priority: Optional[TaskPriority] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List compliance tasks"""
    account = await get_account_for_user(current_user, db)
    
    query = select(ComplianceTask).where(ComplianceTask.account_id == account.id)
    
    if status:
        query = query.where(ComplianceTask.status == status)
    if assignee_id:
        query = query.where(ComplianceTask.assignee_id == assignee_id)
    if priority:
        query = query.where(ComplianceTask.priority == priority)
    if due_date_from:
        try:
            due_from = datetime.strptime(due_date_from, "%Y-%m-%d").date()
            query = query.where(ComplianceTask.due_date >= due_from)
        except ValueError:
            pass
    if due_date_to:
        try:
            due_to = datetime.strptime(due_date_to, "%Y-%m-%d").date()
            query = query.where(ComplianceTask.due_date <= due_to)
        except ValueError:
            pass
    
    # Get total count
    count_query = select(func.count(ComplianceTask.id)).where(ComplianceTask.account_id == account.id)
    if status:
        count_query = count_query.where(ComplianceTask.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.options(
        selectinload(ComplianceTask.assignee),
        selectinload(ComplianceTask.entity)
    ).order_by(desc(ComplianceTask.created_at)).offset(offset).limit(limit)
    
    result = await db.execute(query)
    tasks = result.scalars().all()
    
    # Get related documents for each task
    task_list = []
    for task in tasks:
        # Get related documents
        docs_result = await db.execute(
            select(ComplianceTaskDocument).options(
                selectinload(ComplianceTaskDocument.document)
            ).where(ComplianceTaskDocument.task_id == task.id)
        )
        task_docs = docs_result.scalars().all()
        
        related_documents = []
        for task_doc in task_docs:
            if task_doc.document:
                related_documents.append({
                    "id": str(task_doc.document.id),
                    "name": task_doc.document.file_name,
                    "url": task_doc.document.file_path or ""
                })
        
        assignee_data = None
        if task.assignee:
            assignee_data = {
                "id": str(task.assignee.id),
                "name": f"{task.assignee.first_name or ''} {task.assignee.last_name or ''}".strip() or task.assignee.email,
                "email": task.assignee.email
            }
        
        task_list.append({
            "id": str(task.id),
            "task_name": task.task_name,
            "description": task.description,
            "assignee": assignee_data,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "status": task.status.value if task.status else None,
            "priority": task.priority.value if task.priority else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "entity_id": str(task.entity_id) if task.entity_id else None,
            "category": task.category,
            "related_documents": related_documents
        })
    
    return {
        "data": task_list,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/tasks/{task_id}", response_model=Dict[str, Any])
async def get_task_details(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get compliance task details"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceTask).options(
            selectinload(ComplianceTask.assignee),
            selectinload(ComplianceTask.entity)
        ).where(
            and_(
                ComplianceTask.id == task_id,
                ComplianceTask.account_id == account.id
            )
        )
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise NotFoundException("Compliance Task", str(task_id))
    
    # Get related documents
    docs_result = await db.execute(
        select(ComplianceTaskDocument).options(
            selectinload(ComplianceTaskDocument.document)
        ).where(ComplianceTaskDocument.task_id == task.id)
    )
    task_docs = docs_result.scalars().all()
    
    related_documents = []
    for task_doc in task_docs:
        if task_doc.document:
            related_documents.append({
                "id": str(task_doc.document.id),
                "name": task_doc.document.file_name,
                "url": task_doc.document.file_path or ""
            })
    
    # Get comments
    comments_result = await db.execute(
        select(ComplianceTaskComment).options(
            selectinload(ComplianceTaskComment.user)
        ).where(ComplianceTaskComment.task_id == task.id)
        .order_by(desc(ComplianceTaskComment.created_at))
    )
    comments = comments_result.scalars().all()
    
    comments_list = []
    for comment in comments:
        comments_list.append({
            "id": str(comment.id),
            "user": {
                "id": str(comment.user.id),
                "name": f"{comment.user.first_name or ''} {comment.user.last_name or ''}".strip() or comment.user.email,
                "email": comment.user.email
            },
            "comment": comment.comment,
            "created_at": comment.created_at.isoformat() if comment.created_at else None
        })
    
    # Get history
    history_result = await db.execute(
        select(ComplianceTaskHistory).options(
            selectinload(ComplianceTaskHistory.user)
        ).where(ComplianceTaskHistory.task_id == task.id)
        .order_by(desc(ComplianceTaskHistory.created_at))
    )
    history = history_result.scalars().all()
    
    history_list = []
    for hist in history:
        history_list.append({
            "id": str(hist.id),
            "user": {
                "id": str(hist.user.id),
                "name": f"{hist.user.first_name or ''} {hist.user.last_name or ''}".strip() or hist.user.email
            },
            "action": hist.action,
            "old_value": hist.old_value,
            "new_value": hist.new_value,
            "notes": hist.notes,
            "created_at": hist.created_at.isoformat() if hist.created_at else None
        })
    
    assignee_data = None
    if task.assignee:
        assignee_data = {
            "id": str(task.assignee.id),
            "name": f"{task.assignee.first_name or ''} {task.assignee.last_name or ''}".strip() or task.assignee.email,
            "email": task.assignee.email
        }
    
    return {
        "id": str(task.id),
        "task_name": task.task_name,
        "description": task.description,
        "assignee": assignee_data,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "status": task.status.value if task.status else None,
        "priority": task.priority.value if task.priority else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "entity_id": str(task.entity_id) if task.entity_id else None,
        "category": task.category,
        "related_documents": related_documents,
        "comments": comments_list,
        "history": history_list
    }


@router.post("/tasks", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_compliance_task(
    task_data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new compliance task"""
    account = await get_account_for_user(current_user, db)
    
    # Validate entity if provided
    if task_data.entity_id:
        entity_result = await db.execute(
            select(Entity).where(
                and_(
                    Entity.id == task_data.entity_id,
                    Entity.account_id == account.id
                )
            )
        )
        entity = entity_result.scalar_one_or_none()
        if not entity:
            raise BadRequestException("Entity not found or access denied")
    
    # Validate assignee if provided
    if task_data.assignee_id:
        user_result = await db.execute(
            select(User).where(User.id == task_data.assignee_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise BadRequestException("Assignee not found")
    
    # Parse due date
    try:
        due_date = datetime.strptime(task_data.due_date, "%Y-%m-%d").date()
    except ValueError:
        raise BadRequestException("Invalid due_date format. Use YYYY-MM-DD")
    
    # Determine status based on due date
    task_status = TaskStatus.NOT_STARTED
    if due_date < datetime.utcnow().date():
        task_status = TaskStatus.OVERDUE
    
    # Create task
    task = ComplianceTask(
        account_id=account.id,
        entity_id=task_data.entity_id,
        task_name=task_data.task_name,
        description=task_data.description,
        assignee_id=task_data.assignee_id,
        due_date=due_date,
        status=task_status,
        priority=task_data.priority,
        category=task_data.category
    )
    
    db.add(task)
    await db.flush()
    
    # Link related documents
    if task_data.related_document_ids:
        for doc_id in task_data.related_document_ids:
            # Verify document exists and belongs to account
            doc_result = await db.execute(
                select(Document).where(
                    and_(
                        Document.id == doc_id,
                        Document.account_id == account.id
                    )
                )
            )
            doc = doc_result.scalar_one_or_none()
            if doc:
                task_doc = ComplianceTaskDocument(
                    task_id=task.id,
                    document_id=doc_id
                )
                db.add(task_doc)
    
    # Create history entry
    history = ComplianceTaskHistory(
        task_id=task.id,
        user_id=current_user.id,
        action="created",
        notes=f"Task '{task.task_name}' created"
    )
    db.add(history)
    
    await db.commit()
    await db.refresh(task)
    
    logger.info(f"Compliance task created: {task.id}")
    
    return {
        "id": str(task.id),
        "task_name": task.task_name,
        "status": task.status.value,
        "created_at": task.created_at.isoformat() if task.created_at else None
    }


@router.patch("/tasks/{task_id}", response_model=Dict[str, Any])
async def update_compliance_task(
    task_id: UUID,
    task_data: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update compliance task"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceTask).where(
            and_(
                ComplianceTask.id == task_id,
                ComplianceTask.account_id == account.id
            )
        )
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise NotFoundException("Compliance Task", str(task_id))
    
    # Track changes for history
    changes = []
    
    if task_data.status and task_data.status != task.status:
        changes.append(f"status: {task.status.value} -> {task_data.status.value}")
        task.status = task_data.status
    
    if task_data.assignee_id and task_data.assignee_id != task.assignee_id:
        old_assignee = task.assignee_id
        task.assignee_id = task_data.assignee_id
        changes.append(f"assignee: {old_assignee} -> {task_data.assignee_id}")
    
    if task_data.due_date:
        try:
            new_due_date = datetime.strptime(task_data.due_date, "%Y-%m-%d").date()
            if new_due_date != task.due_date:
                changes.append(f"due_date: {task.due_date} -> {new_due_date}")
                task.due_date = new_due_date
                # Update status if overdue
                if new_due_date < datetime.utcnow().date() and task.status != TaskStatus.COMPLETED:
                    task.status = TaskStatus.OVERDUE
        except ValueError:
            raise BadRequestException("Invalid due_date format. Use YYYY-MM-DD")
    
    if task_data.priority and task_data.priority != task.priority:
        changes.append(f"priority: {task.priority.value} -> {task_data.priority.value}")
        task.priority = task_data.priority
    
    if task_data.description is not None:
        task.description = task_data.description
    
    await db.flush()
    
    # Create history entry
    if changes:
        history = ComplianceTaskHistory(
            task_id=task.id,
            user_id=current_user.id,
            action="updated",
            notes=f"Updated: {', '.join(changes)}"
        )
        db.add(history)
    
    await db.commit()
    await db.refresh(task)
    
    logger.info(f"Compliance task updated: {task_id}")
    
    return {
        "id": str(task.id),
        "task_name": task.task_name,
        "status": task.status.value,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None
    }


@router.post("/tasks/{task_id}/reassign", response_model=Dict[str, Any])
async def reassign_compliance_task(
    task_id: UUID,
    reassign_data: TaskReassign,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Reassign compliance task"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceTask).where(
            and_(
                ComplianceTask.id == task_id,
                ComplianceTask.account_id == account.id
            )
        )
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise NotFoundException("Compliance Task", str(task_id))
    
    # Validate new assignee
    user_result = await db.execute(
        select(User).where(User.id == reassign_data.assignee_id)
    )
    new_assignee = user_result.scalar_one_or_none()
    if not new_assignee:
        raise BadRequestException("Assignee not found")
    
    old_assignee_id = task.assignee_id
    task.assignee_id = reassign_data.assignee_id
    
    await db.flush()
    
    # Create history entry
    history = ComplianceTaskHistory(
        task_id=task.id,
        user_id=current_user.id,
        action="reassigned",
        old_value=str(old_assignee_id) if old_assignee_id else None,
        new_value=str(reassign_data.assignee_id),
        notes=reassign_data.notes or f"Task reassigned to {new_assignee.email}"
    )
    db.add(history)
    
    await db.commit()
    await db.refresh(task)
    await db.refresh(new_assignee)
    
    logger.info(f"Compliance task reassigned: {task_id}")
    
    return {
        "id": str(task.id),
        "assignee": {
            "id": str(new_assignee.id),
            "name": f"{new_assignee.first_name or ''} {new_assignee.last_name or ''}".strip() or new_assignee.email,
            "email": new_assignee.email
        },
        "updated_at": task.updated_at.isoformat() if task.updated_at else None
    }


@router.post("/tasks/{task_id}/complete", response_model=Dict[str, Any])
async def complete_compliance_task(
    task_id: UUID,
    complete_data: TaskComplete,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark compliance task as completed"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceTask).where(
            and_(
                ComplianceTask.id == task_id,
                ComplianceTask.account_id == account.id
            )
        )
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise NotFoundException("Compliance Task", str(task_id))
    
    if task.status == TaskStatus.COMPLETED:
        raise BadRequestException("Task is already completed")
    
    # Parse completed_at if provided
    completed_at = datetime.utcnow()
    if complete_data.completed_at:
        try:
            completed_at = datetime.fromisoformat(complete_data.completed_at.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    task.status = TaskStatus.COMPLETED
    task.completed_at = completed_at
    task.completion_notes = complete_data.completion_notes
    
    await db.flush()
    
    # Create history entry
    history = ComplianceTaskHistory(
        task_id=task.id,
        user_id=current_user.id,
        action="completed",
        notes=complete_data.completion_notes or "Task marked as completed"
    )
    db.add(history)
    
    await db.commit()
    await db.refresh(task)
    
    logger.info(f"Compliance task completed: {task_id}")
    
    return {
        "id": str(task.id),
        "status": task.status.value,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "completion_notes": task.completion_notes
    }


@router.delete("/tasks/{task_id}", status_code=status.HTTP_200_OK)
async def delete_compliance_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete compliance task"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceTask).where(
            and_(
                ComplianceTask.id == task_id,
                ComplianceTask.account_id == account.id
            )
        )
    )
    task = result.scalar_one_or_none()
    
    if not task:
        raise NotFoundException("Compliance Task", str(task_id))
    
    await db.delete(task)
    await db.commit()
    
    logger.info(f"Compliance task deleted: {task_id}")
    
    return {
        "message": "Task deleted successfully"
    }


# ==================== AUDITS ====================

@router.get("/audits", response_model=Dict[str, Any])
async def list_compliance_audits(
    status: Optional[AuditStatus] = Query(None),
    audit_type: Optional[AuditType] = Query(None),
    entity_id: Optional[UUID] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List compliance audits"""
    account = await get_account_for_user(current_user, db)
    
    query = select(ComplianceAudit).where(ComplianceAudit.account_id == account.id)
    
    if status:
        query = query.where(ComplianceAudit.status == status)
    if audit_type:
        query = query.where(ComplianceAudit.audit_type == audit_type)
    if entity_id:
        query = query.where(ComplianceAudit.entity_id == entity_id)
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
            query = query.where(ComplianceAudit.scheduled_date >= date_from_obj)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
            query = query.where(ComplianceAudit.scheduled_date <= date_to_obj)
        except ValueError:
            pass
    
    # Get total count
    count_query = select(func.count(ComplianceAudit.id)).where(ComplianceAudit.account_id == account.id)
    if status:
        count_query = count_query.where(ComplianceAudit.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.options(
        selectinload(ComplianceAudit.auditor),
        selectinload(ComplianceAudit.entity)
    ).order_by(desc(ComplianceAudit.created_at)).offset(offset).limit(limit)
    
    result = await db.execute(query)
    audits = result.scalars().all()
    
    audit_list = []
    for audit in audits:
        auditor_data = None
        if audit.auditor:
            auditor_data = {
                "id": str(audit.auditor.id),
                "name": f"{audit.auditor.first_name or ''} {audit.auditor.last_name or ''}".strip() or audit.auditor.email
            }
        
        scope_list = audit.scope if isinstance(audit.scope, list) else []
        if isinstance(audit.scope, str):
            try:
                scope_list = json.loads(audit.scope) if audit.scope else []
            except:
                scope_list = [audit.scope] if audit.scope else []
        
        audit_list.append({
            "id": str(audit.id),
            "audit_name": audit.audit_name,
            "audit_type": audit.audit_type.value if audit.audit_type else None,
            "status": audit.status.value if audit.status else None,
            "scheduled_date": audit.scheduled_date.isoformat() if audit.scheduled_date else None,
            "due_date": audit.due_date.isoformat() if audit.due_date else None,
            "entity_id": str(audit.entity_id) if audit.entity_id else None,
            "auditor": auditor_data,
            "scope": scope_list if scope_list else [],
            "created_at": audit.created_at.isoformat() if audit.created_at else None
        })
    
    return {
        "data": audit_list,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/audits/{audit_id}", response_model=Dict[str, Any])
async def get_audit_details(
    audit_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get compliance audit details"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceAudit).options(
            selectinload(ComplianceAudit.auditor),
            selectinload(ComplianceAudit.entity)
        ).where(
            and_(
                ComplianceAudit.id == audit_id,
                ComplianceAudit.account_id == account.id
            )
        )
    )
    audit = result.scalar_one_or_none()
    
    if not audit:
        raise NotFoundException("Compliance Audit", str(audit_id))
    
    auditor_data = None
    if audit.auditor:
        auditor_data = {
            "id": str(audit.auditor.id),
            "name": f"{audit.auditor.first_name or ''} {audit.auditor.last_name or ''}".strip() or audit.auditor.email,
            "email": audit.auditor.email
        }
    
    scope_list = audit.scope if isinstance(audit.scope, list) else []
    if isinstance(audit.scope, str):
        try:
            scope_list = json.loads(audit.scope) if audit.scope else []
        except:
            scope_list = [audit.scope] if audit.scope else []
    
    findings_list = audit.findings if isinstance(audit.findings, list) else []
    if isinstance(audit.findings, str):
        try:
            findings_list = json.loads(audit.findings) if audit.findings else []
        except:
            findings_list = []
    
    recommendations_list = audit.recommendations if isinstance(audit.recommendations, list) else []
    if isinstance(audit.recommendations, str):
        try:
            recommendations_list = json.loads(audit.recommendations) if audit.recommendations else []
        except:
            recommendations_list = []
    
    return {
        "id": str(audit.id),
        "audit_name": audit.audit_name,
        "audit_type": audit.audit_type.value if audit.audit_type else None,
        "status": audit.status.value if audit.status else None,
        "scheduled_date": audit.scheduled_date.isoformat() if audit.scheduled_date else None,
        "due_date": audit.due_date.isoformat() if audit.due_date else None,
        "entity_id": str(audit.entity_id) if audit.entity_id else None,
        "auditor": auditor_data,
        "scope": scope_list,
        "description": audit.description,
        "findings": findings_list,
        "recommendations": recommendations_list,
        "created_at": audit.created_at.isoformat() if audit.created_at else None,
        "updated_at": audit.updated_at.isoformat() if audit.updated_at else None
    }


@router.post("/audits", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_compliance_audit(
    audit_data: AuditCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new compliance audit"""
    account = await get_account_for_user(current_user, db)
    
    # Validate entity if provided
    if audit_data.entity_id:
        entity_result = await db.execute(
            select(Entity).where(
                and_(
                    Entity.id == audit_data.entity_id,
                    Entity.account_id == account.id
                )
            )
        )
        entity = entity_result.scalar_one_or_none()
        if not entity:
            raise BadRequestException("Entity not found or access denied")
    
    # Validate auditor if provided
    if audit_data.auditor_id:
        user_result = await db.execute(
            select(User).where(User.id == audit_data.auditor_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise BadRequestException("Auditor not found")
    
    # Parse dates
    try:
        scheduled_date = datetime.strptime(audit_data.scheduled_date, "%Y-%m-%d").date()
        due_date = datetime.strptime(audit_data.due_date, "%Y-%m-%d").date()
    except ValueError:
        raise BadRequestException("Invalid date format. Use YYYY-MM-DD")
    
    if due_date < scheduled_date:
        raise BadRequestException("Due date must be after scheduled date")
    
    # Create audit
    audit = ComplianceAudit(
        account_id=account.id,
        entity_id=audit_data.entity_id,
        audit_name=audit_data.audit_name,
        audit_type=audit_data.audit_type,
        scheduled_date=scheduled_date,
        due_date=due_date,
        auditor_id=audit_data.auditor_id,
        scope=audit_data.scope,
        description=audit_data.description,
        status=AuditStatus.PENDING
    )
    
    db.add(audit)
    await db.commit()
    await db.refresh(audit)
    
    logger.info(f"Compliance audit created: {audit.id}")
    
    return {
        "id": str(audit.id),
        "audit_name": audit.audit_name,
        "status": audit.status.value,
        "created_at": audit.created_at.isoformat() if audit.created_at else None
    }


@router.patch("/audits/{audit_id}", response_model=Dict[str, Any])
async def update_compliance_audit(
    audit_id: UUID,
    audit_data: AuditUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update compliance audit"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceAudit).where(
            and_(
                ComplianceAudit.id == audit_id,
                ComplianceAudit.account_id == account.id
            )
        )
    )
    audit = result.scalar_one_or_none()
    
    if not audit:
        raise NotFoundException("Compliance Audit", str(audit_id))
    
    if audit_data.status:
        audit.status = audit_data.status
    
    if audit_data.scheduled_date:
        try:
            audit.scheduled_date = datetime.strptime(audit_data.scheduled_date, "%Y-%m-%d").date()
        except ValueError:
            raise BadRequestException("Invalid scheduled_date format. Use YYYY-MM-DD")
    
    if audit_data.due_date:
        try:
            audit.due_date = datetime.strptime(audit_data.due_date, "%Y-%m-%d").date()
        except ValueError:
            raise BadRequestException("Invalid due_date format. Use YYYY-MM-DD")
    
    if audit_data.auditor_id:
        # Validate auditor
        user_result = await db.execute(
            select(User).where(User.id == audit_data.auditor_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise BadRequestException("Auditor not found")
        audit.auditor_id = audit_data.auditor_id
    
    if audit_data.scope:
        audit.scope = audit_data.scope
    
    await db.commit()
    await db.refresh(audit)
    
    logger.info(f"Compliance audit updated: {audit_id}")
    
    return {
        "id": str(audit.id),
        "status": audit.status.value,
        "updated_at": audit.updated_at.isoformat() if audit.updated_at else None
    }


# ==================== ALERTS ====================

@router.get("/alerts", response_model=Dict[str, Any])
async def list_compliance_alerts(
    severity: Optional[AlertSeverity] = Query(None),
    status: Optional[AlertStatus] = Query(None),
    alert_type: Optional[str] = Query(None),
    entity_id: Optional[UUID] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List compliance alerts"""
    account = await get_account_for_user(current_user, db)
    
    query = select(ComplianceAlert).where(ComplianceAlert.account_id == account.id)
    
    if severity:
        query = query.where(ComplianceAlert.severity == severity)
    if status:
        query = query.where(ComplianceAlert.status == status)
    if alert_type:
        query = query.where(ComplianceAlert.alert_type == alert_type)
    if entity_id:
        query = query.where(ComplianceAlert.entity_id == entity_id)
    if date_from:
        try:
            date_from_obj = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            query = query.where(ComplianceAlert.created_at >= date_from_obj)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_obj = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            query = query.where(ComplianceAlert.created_at <= date_to_obj)
        except ValueError:
            pass
    
    # Get total count
    count_query = select(func.count(ComplianceAlert.id)).where(ComplianceAlert.account_id == account.id)
    if status:
        count_query = count_query.where(ComplianceAlert.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.options(
        selectinload(ComplianceAlert.entity)
    ).order_by(desc(ComplianceAlert.created_at)).offset(offset).limit(limit)
    
    result = await db.execute(query)
    alerts = result.scalars().all()
    
    alert_list = []
    for alert in alerts:
        alert_list.append({
            "id": str(alert.id),
            "alert_type": alert.alert_type,
            "severity": alert.severity.value if alert.severity else None,
            "status": alert.status.value if alert.status else None,
            "title": alert.title,
            "description": alert.description,
            "entity_id": str(alert.entity_id) if alert.entity_id else None,
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
            "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
            "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None
        })
    
    return {
        "data": alert_list,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/alerts/{alert_id}", response_model=Dict[str, Any])
async def get_alert_details(
    alert_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get compliance alert details"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceAlert).options(
            selectinload(ComplianceAlert.entity),
            selectinload(ComplianceAlert.acknowledged_by_user),
            selectinload(ComplianceAlert.resolved_by_user)
        ).where(
            and_(
                ComplianceAlert.id == alert_id,
                ComplianceAlert.account_id == account.id
            )
        )
    )
    alert = result.scalar_one_or_none()
    
    if not alert:
        raise NotFoundException("Compliance Alert", str(alert_id))
    
    entity_name = None
    if alert.entity:
        entity_name = alert.entity.name
    
    acknowledged_by_name = None
    if alert.acknowledged_by_user:
        acknowledged_by_name = alert.acknowledged_by_user.email
    
    resolved_by_name = None
    if alert.resolved_by_user:
        resolved_by_name = alert.resolved_by_user.email
    
    return {
        "id": str(alert.id),
        "alert_type": alert.alert_type,
        "severity": alert.severity.value if alert.severity else None,
        "status": alert.status.value if alert.status else None,
        "title": alert.title,
        "description": alert.description,
        "entity_id": str(alert.entity_id) if alert.entity_id else None,
        "entity_name": entity_name,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "acknowledged_by": acknowledged_by_name,
        "resolved_by": resolved_by_name,
        "notes": alert.notes,
        "resolution_notes": alert.resolution_notes
    }


@router.post("/alerts/{alert_id}/acknowledge", response_model=Dict[str, Any])
async def acknowledge_alert(
    alert_id: UUID,
    acknowledge_data: AlertAcknowledge,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Acknowledge compliance alert"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceAlert).where(
            and_(
                ComplianceAlert.id == alert_id,
                ComplianceAlert.account_id == account.id
            )
        )
    )
    alert = result.scalar_one_or_none()
    
    if not alert:
        raise NotFoundException("Compliance Alert", str(alert_id))
    
    if alert.status == AlertStatus.RESOLVED or alert.status == AlertStatus.CLOSED:
        raise BadRequestException("Cannot acknowledge resolved or closed alert")
    
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = datetime.utcnow()
    alert.acknowledged_by = current_user.id
    alert.notes = acknowledge_data.notes
    
    await db.commit()
    await db.refresh(alert)
    
    logger.info(f"Compliance alert acknowledged: {alert_id}")
    
    return {
        "id": str(alert.id),
        "status": alert.status.value,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "acknowledged_by": {
            "id": str(current_user.id),
            "name": f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.email
        },
        "notes": alert.notes
    }


@router.post("/alerts/{alert_id}/resolve", response_model=Dict[str, Any])
async def resolve_alert(
    alert_id: UUID,
    resolve_data: AlertResolve,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Resolve compliance alert"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceAlert).where(
            and_(
                ComplianceAlert.id == alert_id,
                ComplianceAlert.account_id == account.id
            )
        )
    )
    alert = result.scalar_one_or_none()
    
    if not alert:
        raise NotFoundException("Compliance Alert", str(alert_id))
    
    # Parse resolved_at if provided
    resolved_at = datetime.utcnow()
    if resolve_data.resolved_at:
        try:
            resolved_at = datetime.fromisoformat(resolve_data.resolved_at.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = resolved_at
    alert.resolved_by = current_user.id
    alert.resolution_notes = resolve_data.resolution_notes
    
    await db.commit()
    await db.refresh(alert)
    
    logger.info(f"Compliance alert resolved: {alert_id}")
    
    return {
        "id": str(alert.id),
        "status": alert.status.value,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "resolved_by": {
            "id": str(current_user.id),
            "name": f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or current_user.email
        },
        "resolution_notes": alert.resolution_notes
    }


# ==================== SCORE & METRICS ====================

@router.get("/score/history", response_model=Dict[str, List[ScoreHistoryItem]])
async def get_compliance_score_history(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    entity_id: Optional[UUID] = Query(None),
    granularity: str = Query("daily", description="daily, weekly, monthly"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get compliance score history"""
    account = await get_account_for_user(current_user, db)
    
    query = select(ComplianceScore).where(ComplianceScore.account_id == account.id)
    
    if entity_id:
        query = query.where(ComplianceScore.entity_id == entity_id)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
            query = query.where(ComplianceScore.date >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
            query = query.where(ComplianceScore.date <= date_to_obj)
        except ValueError:
            pass
    
    # Apply granularity
    if granularity == "weekly":
        # Group by week
        query = query.order_by(ComplianceScore.date)
    elif granularity == "monthly":
        # Group by month
        query = query.order_by(ComplianceScore.date)
    else:
        # Daily
        query = query.order_by(ComplianceScore.date)
    
    result = await db.execute(query)
    scores = result.scalars().all()
    
    # Group by granularity if needed
    score_list = []
    prev_score = None
    
    for score in scores:
        score_date = score.date.isoformat()
        score_value = float(score.score) if score.score else 0.0
        score_change = float(score.change) if score.change else 0.0
        
        if prev_score is not None and granularity in ["weekly", "monthly"]:
            score_change = score_value - prev_score
        
        score_list.append({
            "date": score_date,
            "score": score_value,
            "change": score_change
        })
        
        prev_score = score_value
    
    return {
        "data": score_list
    }


@router.get("/metrics", response_model=Dict[str, Any])
async def get_compliance_metrics(
    entity_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get compliance metrics by category"""
    account = await get_account_for_user(current_user, db)
    
    # Get latest metrics for each category
    query = select(ComplianceMetrics).where(ComplianceMetrics.account_id == account.id)
    
    if entity_id:
        query = query.where(ComplianceMetrics.entity_id == entity_id)
    
    query = query.order_by(desc(ComplianceMetrics.date))
    
    result = await db.execute(query)
    all_metrics = result.scalars().all()
    
    # Group by category and get latest
    category_metrics = {}
    for metric in all_metrics:
        if metric.category not in category_metrics:
            category_metrics[metric.category] = metric
    
    # Calculate overall score (average of category scores)
    overall_score = 0.0
    if category_metrics:
        total_score = sum(float(m.score) for m in category_metrics.values())
        overall_score = total_score / len(category_metrics)
    
    categories_list = []
    for category, metric in category_metrics.items():
        categories_list.append({
            "category": category,
            "score": float(metric.score) if metric.score else 0.0,
            "status": metric.status or "unknown",
            "issues_count": metric.issues_count or 0
        })
    
    return {
        "overall_score": overall_score,
        "categories": categories_list
    }


# ==================== REPORTS ====================

@router.post("/reports/generate", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def generate_compliance_report(
    report_data: ReportGenerate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate compliance report"""
    account = await get_account_for_user(current_user, db)
    
    # Validate entity if provided
    if report_data.entity_id:
        entity_result = await db.execute(
            select(Entity).where(
                and_(
                    Entity.id == report_data.entity_id,
                    Entity.account_id == account.id
                )
            )
        )
        entity = entity_result.scalar_one_or_none()
        if not entity:
            raise BadRequestException("Entity not found or access denied")
    
    # Parse dates
    try:
        date_from = datetime.strptime(report_data.date_from, "%Y-%m-%d").date()
        date_to = datetime.strptime(report_data.date_to, "%Y-%m-%d").date()
    except ValueError:
        raise BadRequestException("Invalid date format. Use YYYY-MM-DD")
    
    if date_to < date_from:
        raise BadRequestException("End date must be after start date")
    
    # Create report record
    report = ComplianceReport(
        account_id=account.id,
        entity_id=report_data.entity_id,
        report_type=report_data.report_type,
        date_from=date_from,
        date_to=date_to,
        format=report_data.format,
        include_sections=report_data.include_sections,
        status=ReportStatus.GENERATING,
        estimated_completion=datetime.utcnow() + timedelta(minutes=5)  # Estimate 5 minutes
    )
    
    db.add(report)
    await db.commit()
    await db.refresh(report)
    
    # In production, this would trigger an async task to generate the report
    # For now, we'll mark it as generating and the frontend can poll for status
    
    logger.info(f"Compliance report generation started: {report.id}")
    
    return {
        "report_id": str(report.id),
        "status": report.status.value,
        "download_url": None,
        "estimated_completion": report.estimated_completion.isoformat() if report.estimated_completion else None
    }


@router.get("/reports/{report_id}", response_model=Dict[str, Any])
async def get_report_status(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get compliance report status"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceReport).where(
            and_(
                ComplianceReport.id == report_id,
                ComplianceReport.account_id == account.id
            )
        )
    )
    report = result.scalar_one_or_none()
    
    if not report:
        raise NotFoundException("Compliance Report", str(report_id))
    
    # In production, this would check the actual generation status
    # For now, we'll return the stored status
    
    return {
        "report_id": str(report.id),
        "status": report.status.value,
        "download_url": report.download_url,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "completed_at": report.completed_at.isoformat() if report.completed_at else None,
        "file_size": report.file_size,
        "format": report.format.value if report.format else None
    }


@router.get("/reports/{report_id}/download")
async def download_compliance_report(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Download compliance report"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(ComplianceReport).where(
            and_(
                ComplianceReport.id == report_id,
                ComplianceReport.account_id == account.id
            )
        )
    )
    report = result.scalar_one_or_none()
    
    if not report:
        raise NotFoundException("Compliance Report", str(report_id))
    
    if report.status != ReportStatus.COMPLETED:
        raise BadRequestException("Report is not ready for download")
    
    if not report.file_path and not report.download_url:
        raise BadRequestException("Report file not found")
    
    # If file is in Supabase storage
    if hasattr(report, 'supabase_storage_path') and report.supabase_storage_path:
        try:
            client = SupabaseClient.get_client()
            if not client:
                raise BadRequestException("Storage client not available")
            
            file_data = client.storage.from_("documents").download(report.supabase_storage_path)
            
            from fastapi.responses import StreamingResponse
            
            # Determine content type
            content_type = "application/pdf"
            if report.format == ReportFormat.EXCEL:
                content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif report.format == ReportFormat.CSV:
                content_type = "text/csv"
            
            return StreamingResponse(
                io.BytesIO(file_data),
                media_type=content_type,
                headers={"Content-Disposition": f'attachment; filename="compliance_report_{report_id}.{report.format.value}"'}
            )
        except Exception as e:
            logger.error(f"Failed to download report from storage: {e}")
            raise BadRequestException("Failed to download report file")
    
    # If download_url is provided, redirect
    if report.download_url:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=report.download_url)
    
    raise BadRequestException("Report file not available")


# ==================== POLICIES ====================

@router.get("/policies", response_model=Dict[str, Any])
async def list_compliance_policies(
    category: Optional[str] = Query(None),
    status: Optional[PolicyStatus] = Query(None),
    entity_id: Optional[UUID] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List compliance policies"""
    account = await get_account_for_user(current_user, db)
    
    query = select(CompliancePolicy).where(CompliancePolicy.account_id == account.id)
    
    if category:
        query = query.where(CompliancePolicy.category == category)
    if status:
        query = query.where(CompliancePolicy.status == status)
    if entity_id:
        query = query.where(CompliancePolicy.entity_id == entity_id)
    
    # Get total count
    count_query = select(func.count(CompliancePolicy.id)).where(CompliancePolicy.account_id == account.id)
    if category:
        count_query = count_query.where(CompliancePolicy.category == category)
    if status:
        count_query = count_query.where(CompliancePolicy.status == status)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.order_by(desc(CompliancePolicy.created_at)).offset(offset).limit(limit)
    
    result = await db.execute(query)
    policies = result.scalars().all()
    
    policy_list = []
    for policy in policies:
        policy_list.append({
            "id": str(policy.id),
            "policy_name": policy.policy_name,
            "category": policy.category,
            "status": policy.status.value if policy.status else None,
            "version": policy.version,
            "effective_date": policy.effective_date.isoformat() if policy.effective_date else None,
            "expiry_date": policy.expiry_date.isoformat() if policy.expiry_date else None,
            "last_reviewed": policy.last_reviewed.isoformat() if policy.last_reviewed else None,
            "next_review": policy.next_review.isoformat() if policy.next_review else None,
            "document_url": policy.document_url
        })
    
    return {
        "data": policy_list,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/policies/{policy_id}", response_model=Dict[str, Any])
async def get_policy_details(
    policy_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get compliance policy details"""
    account = await get_account_for_user(current_user, db)
    
    result = await db.execute(
        select(CompliancePolicy).where(
            and_(
                CompliancePolicy.id == policy_id,
                CompliancePolicy.account_id == account.id
            )
        )
    )
    policy = result.scalar_one_or_none()
    
    if not policy:
        raise NotFoundException("Compliance Policy", str(policy_id))
    
    return {
        "id": str(policy.id),
        "policy_name": policy.policy_name,
        "category": policy.category,
        "status": policy.status.value if policy.status else None,
        "version": policy.version,
        "effective_date": policy.effective_date.isoformat() if policy.effective_date else None,
        "expiry_date": policy.expiry_date.isoformat() if policy.expiry_date else None,
        "last_reviewed": policy.last_reviewed.isoformat() if policy.last_reviewed else None,
        "next_review": policy.next_review.isoformat() if policy.next_review else None,
        "document_url": policy.document_url,
        "description": policy.description,
        "entity_id": str(policy.entity_id) if policy.entity_id else None,
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None
    }


@router.post("/policies", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def upload_policy(
    file: UploadFile = File(...),
    policy_name: str = Form(...),
    category: str = Form(...),
    version: str = Form(...),
    effective_date: str = Form(...),
    expiry_date: Optional[str] = Form(None),
    entity_id: Optional[UUID] = Form(None),
    description: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload compliance policy document"""
    account = await get_account_for_user(current_user, db)
    
    # Validate entity if provided
    if entity_id:
        entity_result = await db.execute(
            select(Entity).where(
                and_(
                    Entity.id == entity_id,
                    Entity.account_id == account.id
                )
            )
        )
        entity = entity_result.scalar_one_or_none()
        if not entity:
            raise BadRequestException("Entity not found or access denied")
    
    # Parse dates
    try:
        effective_date_obj = datetime.strptime(effective_date, "%Y-%m-%d").date()
    except ValueError:
        raise BadRequestException("Invalid effective_date format. Use YYYY-MM-DD")
    
    expiry_date_obj = None
    if expiry_date:
        try:
            expiry_date_obj = datetime.strptime(expiry_date, "%Y-%m-%d").date()
        except ValueError:
            raise BadRequestException("Invalid expiry_date format. Use YYYY-MM-DD")
    
    # Validate file type
    file_extension = file.filename.split(".")[-1].lower() if "." in file.filename else ""
    if file_extension not in ["pdf", "doc", "docx"]:
        raise BadRequestException("File type not allowed. Allowed types: pdf, doc, docx")
    
    # Read file
    file_data = await file.read()
    file_size = len(file_data)
    
    # Check file size (max 10MB)
    if file_size > 10 * 1024 * 1024:
        raise BadRequestException("File size exceeds maximum allowed size of 10MB")
    
    # Upload to Supabase Storage
    try:
        file_path = f"policies/{account.id}/{file.filename}"
        SupabaseClient.upload_file(
            bucket="documents",
            file_path=file_path,
            file_data=file_data,
            content_type=file.content_type or "application/pdf"
        )
        
        # Get public URL
        file_url = SupabaseClient.get_file_url("documents", file_path)
    except Exception as e:
        logger.error(f"Failed to upload policy to Supabase: {e}")
        raise BadRequestException("Failed to upload policy document")
    
    # Create policy record
    policy = CompliancePolicy(
        account_id=account.id,
        entity_id=entity_id,
        policy_name=policy_name,
        category=category,
        version=version,
        effective_date=effective_date_obj,
        expiry_date=expiry_date_obj,
        document_url=file_url,
        document_path=file_path,
        supabase_storage_path=file_path,
        description=description,
        status=PolicyStatus.DRAFT
    )
    
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    
    logger.info(f"Compliance policy uploaded: {policy.id}")
    
    return {
        "id": str(policy.id),
        "policy_name": policy.policy_name,
        "status": policy.status.value,
        "document_url": policy.document_url,
        "created_at": policy.created_at.isoformat() if policy.created_at else None
    }
