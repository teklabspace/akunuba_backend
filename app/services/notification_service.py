from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.account import Account
from app.models.user import User
from app.models.notification import Notification, NotificationType
from app.services.email_service import EmailService
from app.utils.logger import logger
from datetime import datetime
from uuid import UUID


class NotificationService:
    @staticmethod
    async def create_notification(
        db: AsyncSession,
        account_id: UUID,
        notification_type: NotificationType,
        title: str,
        message: str,
        metadata: str = None,
        send_email: bool = True
    ) -> Notification:
        """Create a notification and optionally send email"""
        notification = Notification(
            account_id=account_id,
            notification_type=notification_type,
            title=title,
            message=message,
            metadata=metadata,
        )
        
        db.add(notification)
        await db.commit()
        await db.refresh(notification)
        
        logger.info(f"Notification created: {notification.id} for account {account_id}")
        
        # Send email notification if enabled
        if send_email:
            await NotificationService._send_notification_email(db, notification)
        
        return notification
    
    @staticmethod
    async def _send_notification_email(db: AsyncSession, notification: Notification):
        """Send email for a notification"""
        try:
            # Get account and user
            account_result = await db.execute(
                select(Account).where(Account.id == notification.account_id)
            )
            account = account_result.scalar_one_or_none()
            
            if not account:
                logger.warning(f"Account not found for notification {notification.id}")
                return
            
            user_result = await db.execute(
                select(User).where(User.id == account.user_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user or not user.email:
                logger.warning(f"User email not found for notification {notification.id}")
                return
            
            # Send email
            email_sent = await EmailService.send_notification_email(
                to_email=user.email,
                to_name=f"{user.first_name or ''} {user.last_name or ''}".strip() or "User",
                notification_title=notification.title,
                notification_message=notification.message,
                notification_type=notification.notification_type.value
            )
            
            if email_sent:
                notification.email_sent = True
                notification.email_sent_at = datetime.utcnow()
                await db.commit()
                logger.info(f"Email sent for notification {notification.id}")
            else:
                logger.warning(f"Failed to send email for notification {notification.id}")
                
        except Exception as e:
            logger.error(f"Error sending email for notification {notification.id}: {e}")


async def create_notification(
    db: AsyncSession,
    account_id: UUID,
    notification_type: NotificationType,
    title: str,
    message: str,
    metadata: str = None
) -> Notification:
    """Helper function to create notifications (backward compatibility)"""
    return await NotificationService.create_notification(
        db, account_id, notification_type, title, message, metadata
    )

