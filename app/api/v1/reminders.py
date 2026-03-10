from fastapi import APIRouter, Depends, Query, Body, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc, func
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.task import Reminder, ReminderStatus
from app.core.exceptions import NotFoundException, BadRequestException
from app.utils.logger import logger
from pydantic import BaseModel, Field
import json


router = APIRouter()


class ReminderResponse(BaseModel):
    id: UUID
    title: str
    description: Optional[str] = None
    reminderDate: datetime
    status: str
    taskId: Optional[UUID] = None
    notificationChannels: Optional[List[str]] = None
    snoozedUntil: Optional[datetime] = None
    createdAt: datetime
    updatedAt: Optional[datetime] = None

    class Config:
        from_attributes = True


class RemindersListResponse(BaseModel):
    data: List[ReminderResponse]
    total: int
    limit: int
    offset: int


class ReminderCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    reminderDate: datetime
    taskId: Optional[UUID] = None
    notificationChannels: Optional[List[str]] = None


class ReminderUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    reminderDate: Optional[datetime] = None
    notificationChannels: Optional[List[str]] = None


class ReminderSnoozeRequest(BaseModel):
    snoozeUntil: datetime


def _parse_channels(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        # Fallback for legacy comma-separated format
        return [c for c in raw.split(",") if c]


def _serialize_channels(channels: Optional[List[str]]) -> Optional[str]:
    if channels is None:
        return None
    return json.dumps(channels)


@router.get("", response_model=RemindersListResponse)
async def get_reminders(
    status: Optional[str] = Query(None, description="pending | snoozed | completed | cancelled"),
    due_date_from: Optional[str] = Query(None, description="ISO 8601 date"),
    due_date_to: Optional[str] = Query(None, description="ISO 8601 date"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get reminders for the current user"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    query = select(Reminder).where(Reminder.account_id == account.id)

    if status:
        try:
            status_enum = ReminderStatus(status.lower())
            query = query.where(Reminder.status == status_enum)
        except ValueError:
            raise BadRequestException("Invalid status value")

    if due_date_from:
        try:
            from_dt = datetime.fromisoformat(due_date_from.replace("Z", "+00:00"))
            query = query.where(Reminder.reminder_date >= from_dt)
        except ValueError:
            raise BadRequestException("Invalid due_date_from format")

    if due_date_to:
        try:
            to_dt = datetime.fromisoformat(due_date_to.replace("Z", "+00:00"))
            query = query.where(Reminder.reminder_date <= to_dt)
        except ValueError:
            raise BadRequestException("Invalid due_date_to format")

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(desc(Reminder.reminder_date)).offset(offset).limit(limit)
    result = await db.execute(query)
    reminders = result.scalars().all()

    response_items: List[ReminderResponse] = []
    for r in reminders:
        response_items.append(
            ReminderResponse(
                id=r.id,
                title=r.title,
                description=r.description,
                reminderDate=r.reminder_date,
                status=r.status.value,
                taskId=r.task_id,
                notificationChannels=_parse_channels(r.notification_channels),
                snoozedUntil=r.snoozed_until,
                createdAt=r.created_at,
                updatedAt=r.updated_at,
            )
        )

    return RemindersListResponse(
        data=response_items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=Dict[str, ReminderResponse], status_code=status.HTTP_201_CREATED)
async def create_reminder(
    reminder_data: ReminderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a reminder"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    reminder = Reminder(
        account_id=account.id,
        task_id=reminder_data.taskId,
        title=reminder_data.title,
        description=reminder_data.description,
        reminder_date=reminder_data.reminderDate,
        status=ReminderStatus.PENDING,
        notification_channels=_serialize_channels(reminder_data.notificationChannels),
    )

    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)

    logger.info(f"Reminder created: {reminder.id}")

    return {
        "reminder": ReminderResponse(
            id=reminder.id,
            title=reminder.title,
            description=reminder.description,
            reminderDate=reminder.reminder_date,
            status=reminder.status.value,
            taskId=reminder.task_id,
            notificationChannels=_parse_channels(reminder.notification_channels),
            snoozedUntil=reminder.snoozed_until,
            createdAt=reminder.created_at,
            updatedAt=reminder.updated_at,
        )
    }


@router.put("/{reminder_id}", response_model=Dict[str, ReminderResponse])
async def update_reminder(
    reminder_id: UUID,
    reminder_data: ReminderUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a reminder"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    reminder_result = await db.execute(
        select(Reminder).where(
            and_(
                Reminder.id == reminder_id,
                Reminder.account_id == account.id,
            )
        )
    )
    reminder = reminder_result.scalar_one_or_none()

    if not reminder:
        raise NotFoundException("Reminder", str(reminder_id))

    if reminder_data.title is not None:
        reminder.title = reminder_data.title
    if reminder_data.description is not None:
        reminder.description = reminder_data.description
    if reminder_data.reminderDate is not None:
        reminder.reminder_date = reminder_data.reminderDate
    if reminder_data.notificationChannels is not None:
        reminder.notification_channels = _serialize_channels(reminder_data.notificationChannels)

    await db.commit()
    await db.refresh(reminder)

    logger.info(f"Reminder updated: {reminder.id}")

    return {
        "reminder": ReminderResponse(
            id=reminder.id,
            title=reminder.title,
            description=reminder.description,
            reminderDate=reminder.reminder_date,
            status=reminder.status.value,
            taskId=reminder.task_id,
            notificationChannels=_parse_channels(reminder.notification_channels),
            snoozedUntil=reminder.snoozed_until,
            createdAt=reminder.created_at,
            updatedAt=reminder.updated_at,
        )
    }


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(
    reminder_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a reminder"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    reminder_result = await db.execute(
        select(Reminder).where(
            and_(
                Reminder.id == reminder_id,
                Reminder.account_id == account.id,
            )
        )
    )
    reminder = reminder_result.scalar_one_or_none()

    if not reminder:
        raise NotFoundException("Reminder", str(reminder_id))

    await db.delete(reminder)
    await db.commit()

    logger.info(f"Reminder deleted: {reminder_id}")
    return None


@router.put("/{reminder_id}/snooze", response_model=Dict[str, ReminderResponse])
async def snooze_reminder(
    reminder_id: UUID,
    snooze_data: ReminderSnoozeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Snooze a reminder"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    reminder_result = await db.execute(
        select(Reminder).where(
            and_(
                Reminder.id == reminder_id,
                Reminder.account_id == account.id,
            )
        )
    )
    reminder = reminder_result.scalar_one_or_none()

    if not reminder:
        raise NotFoundException("Reminder", str(reminder_id))

    reminder.status = ReminderStatus.SNOOZED
    reminder.snoozed_until = snooze_data.snoozeUntil
    reminder.reminder_date = snooze_data.snoozeUntil

    await db.commit()
    await db.refresh(reminder)

    logger.info(f"Reminder snoozed: {reminder.id}")

    return {
        "reminder": ReminderResponse(
            id=reminder.id,
            title=reminder.title,
            description=reminder.description,
            reminderDate=reminder.reminder_date,
            status=reminder.status.value,
            taskId=reminder.task_id,
            notificationChannels=_parse_channels(reminder.notification_channels),
            snoozedUntil=reminder.snoozed_until,
            createdAt=reminder.created_at,
            updatedAt=reminder.updated_at,
        )
    }

