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
        """Create a notification and optionally send email.

        Resolves the owning user so the notification is user-addressable: the bell
        (GET /notifications) and realtime WS both key off ``user_id``. Also pushes
        the notification over WebSocket for live delivery.
        """
        owner_user_id = (await db.execute(
            select(Account.user_id).where(Account.id == account_id)
        )).scalar_one_or_none()

        notification = Notification(
            user_id=owner_user_id,
            account_id=account_id,
            notification_type=notification_type,
            title=title,
            message=message,
            meta_data=metadata,
        )

        db.add(notification)
        await db.commit()
        await db.refresh(notification)

        logger.info(f"Notification created: {notification.id} for account {account_id} (user {owner_user_id})")

        if owner_user_id:
            await NotificationService._push_ws(notification, owner_user_id)

        # Send email notification if enabled
        if send_email:
            await NotificationService._send_notification_email(db, notification)

        return notification

    @staticmethod
    async def notify_user(
        db: AsyncSession,
        user_id: UUID,
        notification_type: NotificationType,
        title: str,
        message: str,
        metadata: str = None,
        send_email: bool = False,
    ) -> Notification:
        """Create a user-addressable notification (bell + realtime) for ANY user,
        including staff (advisors/admins) who may have no account."""
        account_id = (await db.execute(
            select(Account.id).where(Account.user_id == user_id)
        )).scalar_one_or_none()

        notification = Notification(
            user_id=user_id,
            account_id=account_id,
            notification_type=notification_type,
            title=title,
            message=message,
            meta_data=metadata,
        )
        db.add(notification)
        await db.commit()
        await db.refresh(notification)

        await NotificationService._push_ws(notification, user_id)
        if send_email and account_id:
            await NotificationService._send_notification_email(db, notification)

        logger.info(f"Notification created: {notification.id} for user {user_id}")
        return notification

    @staticmethod
    async def _push_ws(notification: Notification, user_id) -> None:
        """Best-effort realtime push so the bell updates live. Never raises."""
        try:
            from app.core.websocket_manager import manager
            from app.api.v1.notifications import serialize_notification
            await manager.send_to_user(user_id, serialize_notification(notification))
        except Exception as e:
            logger.error(f"WS push failed for notification {notification.id}: {e}")
    
    @staticmethod
    async def notify_admins(
        db: AsyncSession,
        notification_type: NotificationType,
        title: str,
        message: str,
        metadata: str = None,
        send_email: bool = False,
    ) -> int:
        """Create a notification for every admin user's account.

        Used for platform events that admins need to act on (new support
        tickets, disputes, KYC submissions, etc.). Notifications are scoped by
        ``account_id``, so this fans the event out to each admin's account.

        Returns the number of notifications created. Admins without an Account
        record are skipped (they cannot view notifications anyway).
        """
        from app.core.permissions import Role

        result = await db.execute(
            select(Account)
            .join(User, Account.user_id == User.id)
            .where(User.role == Role.ADMIN)
        )
        accounts = result.scalars().all()

        created = []
        for account in accounts:
            notification = Notification(
                user_id=account.user_id,  # user-addressable so the bell/WS pick it up
                account_id=account.id,
                notification_type=notification_type,
                title=title,
                message=message,
                meta_data=metadata,
            )
            db.add(notification)
            created.append((notification, account.user_id))

        if not created:
            logger.warning(f"notify_admins: no admin accounts found for '{title}'")
            return 0

        await db.commit()
        for notification, user_id in created:
            await db.refresh(notification)
            await NotificationService._push_ws(notification, user_id)

        logger.info(f"notify_admins: created {len(created)} admin notification(s) for '{title}'")

        if send_email:
            for notification, _ in created:
                await NotificationService._send_notification_email(db, notification)

        return len(created)

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

