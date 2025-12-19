from fastapi import APIRouter, Depends, Query, Body, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from datetime import datetime
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.notification import Notification, NotificationType
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Role, Permission, has_permission
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


class NotificationResponse(BaseModel):
    id: UUID
    notification_type: str
    title: str
    message: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[NotificationResponse])
async def get_notifications(
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get notifications"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(Notification).where(Notification.account_id == account.id)
    
    if unread_only:
        query = query.where(Notification.is_read == False)
    
    result = await db.execute(query.order_by(Notification.created_at.desc()))
    notifications = result.scalars().all()
    
    return notifications


@router.post("/{notification_id}/read")
async def mark_as_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark notification as read"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.id == notification_id,
                Notification.account_id == account.id
            )
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise NotFoundException("Notification", str(notification_id))
    
    notification.is_read = True
    notification.read_at = datetime.utcnow()
    
    await db.commit()
    
    return {"message": "Notification marked as read"}


@router.post("/read-all")
async def mark_all_as_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark all notifications as read"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.account_id == account.id,
                Notification.is_read == False
            )
        )
    )
    notifications = result.scalars().all()
    
    for notification in notifications:
        notification.is_read = True
        notification.read_at = datetime.utcnow()
    
    await db.commit()
    
    return {"message": f"{len(notifications)} notifications marked as read"}


@router.get("/unread-count")
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get unread notification count"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        return {"count": 0}
    
    result = await db.execute(
        select(Notification).where(
            and_(
                Notification.account_id == account.id,
                Notification.is_read == False
            )
        )
    )
    count = len(result.scalars().all())
    
    return {"count": count}


class NotificationCreate(BaseModel):
    account_id: UUID
    notification_type: NotificationType
    title: str
    message: str
    metadata: Optional[str] = None


@router.post("", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
async def create_notification(
    notification_data: NotificationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a notification (admin or system only)"""
    if not has_permission(current_user.role, Permission.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Verify account exists
    account_result = await db.execute(
        select(Account).where(Account.id == notification_data.account_id)
    )
    if not account_result.scalar_one_or_none():
        raise NotFoundException("Account", str(notification_data.account_id))
    
    notification = Notification(
        account_id=notification_data.account_id,
        notification_type=notification_data.notification_type,
        title=notification_data.title,
        message=notification_data.message,
        meta_data=notification_data.metadata,
        is_read=False
    )
    
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    
    logger.info(f"Notification created: {notification.id}")
    return notification


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a notification"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.account_id == account.id
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise NotFoundException("Notification", str(notification_id))
    
    await db.delete(notification)
    await db.commit()
    
    logger.info(f"Notification deleted: {notification_id}")
    return None


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_notifications(
    read_only: bool = Query(False, description="Delete only read notifications"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete all notifications (or only read ones)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    query = select(Notification).where(Notification.account_id == account.id)
    if read_only:
        query = query.where(Notification.is_read == True)
    
    result = await db.execute(query)
    notifications = result.scalars().all()
    
    for notification in notifications:
        await db.delete(notification)
    
    await db.commit()
    
    logger.info(f"Deleted {len(notifications)} notifications")
    return None

