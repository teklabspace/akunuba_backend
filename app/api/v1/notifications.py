from fastapi import APIRouter, Depends, Query, Body, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
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


def serialize_notification(n: Notification) -> Dict[str, Any]:
    """Flatten a Notification (+ its JSON metadata) into the shape the frontend
    consumes for both the bell and the WS popup."""
    meta = {}
    if n.meta_data:
        try:
            meta = json.loads(n.meta_data)
        except Exception:
            meta = {}
    return {
        "id": str(n.id),
        "notification_id": str(n.id),
        # Precise event type from metadata (e.g. appraisal_created /
        # appraisal_message); falls back to the coarse DB enum.
        "type": meta.get("type") or n.notification_type.value,
        "notification_type": n.notification_type.value,
        "title": n.title,
        "message": n.message,
        "preview": meta.get("preview", n.message),
        "appraisal_id": meta.get("appraisal_id"),
        "asset_id": meta.get("asset_id"),
        "asset_code": meta.get("asset_code"),
        "asset_name": meta.get("asset_name"),
        "appraisal_type": meta.get("appraisal_type"),
        "author_kind": meta.get("author_kind"),
        "author_name": meta.get("author_name"),
        "read": n.is_read,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("", response_model=List[Dict[str, Any]])
async def get_notifications(
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the current user's notifications (newest first)."""
    query = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        query = query.where(Notification.is_read == False)

    result = await db.execute(query.order_by(Notification.created_at.desc()))
    return [serialize_notification(n) for n in result.scalars().all()]


@router.post("/{notification_id}/read")
async def mark_as_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark a notification as read."""
    result = await db.execute(
        select(Notification).where(and_(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        ))
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
    """Mark all of the user's notifications as read."""
    result = await db.execute(
        select(Notification).where(and_(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
        ))
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
    """Get the user's unread notification count."""
    count = (await db.execute(
        select(func.count(Notification.id)).where(and_(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
        ))
    )).scalar() or 0
    return {"count": count}


@router.get("/unread", response_model=List[Dict[str, Any]])
async def get_unread_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the user's unread notifications (newest first)."""
    result = await db.execute(
        select(Notification).where(and_(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
        )).order_by(Notification.created_at.desc())
    )
    return [serialize_notification(n) for n in result.scalars().all()]


class NotificationSettingsResponse(BaseModel):
    email_enabled: bool
    push_enabled: bool
    sms_enabled: bool
    order_notifications: bool
    offer_notifications: bool
    payment_notifications: bool
    kyc_notifications: bool
    support_notifications: bool
    general_notifications: bool


class NotificationSettingsUpdate(BaseModel):
    email_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None
    order_notifications: Optional[bool] = None
    offer_notifications: Optional[bool] = None
    payment_notifications: Optional[bool] = None
    kyc_notifications: Optional[bool] = None
    support_notifications: Optional[bool] = None
    general_notifications: Optional[bool] = None


@router.get("/settings", response_model=NotificationSettingsResponse)
async def get_notification_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get notification settings"""
    # In a real implementation, this would come from UserPreferences
    # For now, return defaults
    return NotificationSettingsResponse(
        email_enabled=True,
        push_enabled=True,
        sms_enabled=False,
        order_notifications=True,
        offer_notifications=True,
        payment_notifications=True,
        kyc_notifications=True,
        support_notifications=True,
        general_notifications=True
    )


@router.put("/settings", response_model=NotificationSettingsResponse)
async def update_notification_settings(
    settings: NotificationSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update notification settings"""
    # In a real implementation, this would update UserPreferences
    # For now, return the updated settings
    return NotificationSettingsResponse(
        email_enabled=settings.email_enabled if settings.email_enabled is not None else True,
        push_enabled=settings.push_enabled if settings.push_enabled is not None else True,
        sms_enabled=settings.sms_enabled if settings.sms_enabled is not None else False,
        order_notifications=settings.order_notifications if settings.order_notifications is not None else True,
        offer_notifications=settings.offer_notifications if settings.offer_notifications is not None else True,
        payment_notifications=settings.payment_notifications if settings.payment_notifications is not None else True,
        kyc_notifications=settings.kyc_notifications if settings.kyc_notifications is not None else True,
        support_notifications=settings.support_notifications if settings.support_notifications is not None else True,
        general_notifications=settings.general_notifications if settings.general_notifications is not None else True
    )


class NotificationCreate(BaseModel):
    account_id: UUID
    notification_type: NotificationType
    title: str
    message: str
    metadata: Optional[str] = None


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
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
    
    # Resolve the owning user so the notification is user-addressable.
    owner_user_id = (await db.execute(
        select(Account.user_id).where(Account.id == notification_data.account_id)
    )).scalar_one_or_none()

    notification = Notification(
        user_id=owner_user_id,
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
    return serialize_notification(notification)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a notification"""
    result = await db.execute(
        select(Notification).where(and_(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        ))
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
    query = select(Notification).where(Notification.user_id == current_user.id)
    if read_only:
        query = query.where(Notification.is_read == True)

    result = await db.execute(query)
    notifications = result.scalars().all()
    
    for notification in notifications:
        await db.delete(notification)
    
    await db.commit()
    
    logger.info(f"Deleted {len(notifications)} notifications")
    return None

