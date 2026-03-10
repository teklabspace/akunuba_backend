from fastapi import APIRouter, Depends, Query, Body, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.task import Task, Reminder, TaskStatus, TaskPriority, ReminderStatus
from app.core.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger
from pydantic import BaseModel, Field

router = APIRouter()


class TaskResponse(BaseModel):
    id: UUID
    title: str
    description: Optional[str] = None
    status: str
    priority: str
    category: Optional[str] = None
    dueDate: Optional[datetime] = None
    reminderDate: Optional[datetime] = None
    completedAt: Optional[datetime] = None
    createdAt: datetime
    updatedAt: Optional[datetime] = None

    class Config:
        from_attributes = True


class TasksListResponse(BaseModel):
    data: List[TaskResponse]
    total: int
    limit: int
    offset: int


class TaskCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    priority: Optional[str] = Field("medium", pattern="^(low|medium|high|urgent)$")
    category: Optional[str] = Field(None, max_length=100)
    dueDate: Optional[datetime] = None
    reminderDate: Optional[datetime] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    priority: Optional[str] = Field(None, pattern="^(low|medium|high|urgent)$")
    category: Optional[str] = Field(None, max_length=100)
    dueDate: Optional[datetime] = None
    reminderDate: Optional[datetime] = None


class ReminderSetRequest(BaseModel):
    reminderDate: datetime


@router.get("", response_model=TasksListResponse)
async def get_tasks(
    status: Optional[str] = Query(None, description="Filter by status: pending, in_progress, completed, cancelled"),
    priority: Optional[str] = Query(None, description="Filter by priority: low, medium, high, urgent"),
    category: Optional[str] = Query(None),
    due_date_from: Optional[str] = Query(None, description="ISO 8601 date"),
    due_date_to: Optional[str] = Query(None, description="ISO 8601 date"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user tasks"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(Task).where(Task.account_id == account.id)
    
    if status:
        try:
            status_enum = TaskStatus(status.lower())
            query = query.where(Task.status == status_enum)
        except ValueError:
            pass
    
    if priority:
        try:
            priority_enum = TaskPriority(priority.lower())
            query = query.where(Task.priority == priority_enum)
        except ValueError:
            pass
    
    if category:
        query = query.where(Task.category == category)
    
    if due_date_from:
        try:
            from_dt = datetime.fromisoformat(due_date_from.replace("Z", "+00:00"))
            query = query.where(Task.due_date >= from_dt)
        except ValueError:
            pass
    
    if due_date_to:
        try:
            to_dt = datetime.fromisoformat(due_date_to.replace("Z", "+00:00"))
            query = query.where(Task.due_date <= to_dt)
        except ValueError:
            pass
    
    # Get total count
    from sqlalchemy import func
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.order_by(desc(Task.created_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    tasks = result.scalars().all()
    
    return TasksListResponse(
        data=[TaskResponse.model_validate(t) for t in tasks],
        total=total,
        limit=limit,
        offset=offset
    )


@router.post("", response_model=Dict[str, TaskResponse], status_code=status.HTTP_201_CREATED)
async def create_task(
    task_data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a task"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    priority = TaskPriority(task_data.priority.lower()) if task_data.priority else TaskPriority.MEDIUM
    
    task = Task(
        account_id=account.id,
        title=task_data.title,
        description=task_data.description,
        priority=priority,
        category=task_data.category,
        due_date=task_data.dueDate,
        reminder_date=task_data.reminderDate,
        status=TaskStatus.PENDING
    )
    
    db.add(task)
    await db.commit()
    await db.refresh(task)
    
    logger.info(f"Task created: {task.id}")
    return {"task": TaskResponse.model_validate(task)}


@router.get("/{task_id}", response_model=Dict[str, TaskResponse])
async def get_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get task details"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    task_result = await db.execute(
        select(Task).where(
            and_(
                Task.id == task_id,
                Task.account_id == account.id
            )
        )
    )
    task = task_result.scalar_one_or_none()
    
    if not task:
        raise NotFoundException("Task", str(task_id))
    
    return {"task": TaskResponse.model_validate(task)}


@router.put("/{task_id}", response_model=Dict[str, TaskResponse])
async def update_task(
    task_id: UUID,
    task_data: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a task"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    task_result = await db.execute(
        select(Task).where(
            and_(
                Task.id == task_id,
                Task.account_id == account.id
            )
        )
    )
    task = task_result.scalar_one_or_none()
    
    if not task:
        raise NotFoundException("Task", str(task_id))
    
    if task_data.title is not None:
        task.title = task_data.title
    if task_data.description is not None:
        task.description = task_data.description
    if task_data.priority is not None:
        task.priority = TaskPriority(task_data.priority.lower())
    if task_data.category is not None:
        task.category = task_data.category
    if task_data.dueDate is not None:
        task.due_date = task_data.dueDate
    if task_data.reminderDate is not None:
        task.reminder_date = task_data.reminderDate
    
    await db.commit()
    await db.refresh(task)
    
    logger.info(f"Task updated: {task.id}")
    return {"task": TaskResponse.model_validate(task)}


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a task"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    task_result = await db.execute(
        select(Task).where(
            and_(
                Task.id == task_id,
                Task.account_id == account.id
            )
        )
    )
    task = task_result.scalar_one_or_none()
    
    if not task:
        raise NotFoundException("Task", str(task_id))
    
    await db.delete(task)
    await db.commit()
    
    logger.info(f"Task deleted: {task_id}")
    return None


@router.put("/{task_id}/complete", response_model=Dict[str, TaskResponse])
async def complete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark task as complete"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    task_result = await db.execute(
        select(Task).where(
            and_(
                Task.id == task_id,
                Task.account_id == account.id
            )
        )
    )
    task = task_result.scalar_one_or_none()
    
    if not task:
        raise NotFoundException("Task", str(task_id))
    
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(task)
    
    logger.info(f"Task completed: {task.id}")
    return {"task": TaskResponse.model_validate(task)}


@router.put("/{task_id}/remind", response_model=Dict[str, TaskResponse])
async def set_task_reminder(
    task_id: UUID,
    reminder_data: ReminderSetRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Set reminder for a task"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    task_result = await db.execute(
        select(Task).where(
            and_(
                Task.id == task_id,
                Task.account_id == account.id
            )
        )
    )
    task = task_result.scalar_one_or_none()
    
    if not task:
        raise NotFoundException("Task", str(task_id))
    
    task.reminder_date = reminder_data.reminderDate
    
    await db.commit()
    await db.refresh(task)
    
    logger.info(f"Reminder set for task: {task.id}")
    return {"task": TaskResponse.model_validate(task)}
