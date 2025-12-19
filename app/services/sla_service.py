from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from app.models.support import SupportTicket, TicketStatus, TicketPriority
from app.models.user import User
from app.models.account import Account
from app.core.exceptions import NotFoundException
from app.core.permissions import Role
from app.utils.logger import logger


class SLAService:
    # SLA targets in hours
    SLA_TARGETS = {
        TicketPriority.LOW: {
            "first_response": 48,
            "resolution": 168  # 7 days
        },
        TicketPriority.MEDIUM: {
            "first_response": 24,
            "resolution": 72  # 3 days
        },
        TicketPriority.HIGH: {
            "first_response": 4,
            "resolution": 24
        },
        TicketPriority.URGENT: {
            "first_response": 1,
            "resolution": 8
        }
    }
    
    @staticmethod
    async def calculate_sla_targets(priority: TicketPriority) -> dict:
        """Calculate SLA targets for a ticket priority"""
        return SLAService.SLA_TARGETS.get(priority, SLAService.SLA_TARGETS[TicketPriority.MEDIUM])
    
    @staticmethod
    async def set_sla_targets(db: AsyncSession, ticket: SupportTicket):
        """Set SLA targets for a ticket based on priority"""
        targets = await SLAService.calculate_sla_targets(ticket.priority)
        ticket.sla_target_hours = targets["resolution"]
        
        if not ticket.first_response_at:
            first_response_deadline = datetime.utcnow() + timedelta(hours=targets["first_response"])
            # Store in metadata or separate field if needed
    
    @staticmethod
    async def check_sla_breach(db: AsyncSession, ticket: SupportTicket) -> bool:
        """Check if ticket has breached SLA"""
        if not ticket.sla_target_hours:
            await SLAService.set_sla_targets(db, ticket)
            await db.commit()
            await db.refresh(ticket)
        
        if ticket.status in [TicketStatus.RESOLVED, TicketStatus.CLOSED]:
            return False
        
        # Check first response SLA
        if not ticket.first_response_at:
            targets = await SLAService.calculate_sla_targets(ticket.priority)
            hours_since_creation = (datetime.utcnow() - ticket.created_at).total_seconds() / 3600
            if hours_since_creation > targets["first_response"]:
                return True
        
        # Check resolution SLA
        hours_since_creation = (datetime.utcnow() - ticket.created_at).total_seconds() / 3600
        if hours_since_creation > ticket.sla_target_hours:
            return True
        
        return False
    
    @staticmethod
    async def escalate_ticket(db: AsyncSession, ticket: SupportTicket):
        """Escalate a ticket"""
        from app.services.notification_service import NotificationService, NotificationType
        from app.models.account import Account
        from app.core.permissions import Role
        
        # Find admin users
        admin_result = await db.execute(
            select(User).where(User.role == Role.ADMIN, User.is_active == True)
        )
        admins = admin_result.scalars().all()
        
        # Notify admins
        for admin in admins:
            admin_account_result = await db.execute(
                select(Account).where(Account.user_id == admin.id)
            )
            admin_account = admin_account_result.scalar_one_or_none()
            if admin_account:
                await NotificationService.create_notification(
                    db=db,
                    account_id=admin_account.id,
                    notification_type=NotificationType.SUPPORT_REPLY,
                    title="Ticket Escalated",
                    message=f"Ticket {ticket.id} has been escalated due to SLA breach"
                )
        
        ticket.last_escalated_at = datetime.utcnow()
        logger.info(f"Ticket {ticket.id} escalated due to SLA breach")
    
    @staticmethod
    async def record_first_response(db: AsyncSession, ticket: SupportTicket):
        """Record first response time"""
        if not ticket.first_response_at:
            ticket.first_response_at = datetime.utcnow()
            await db.commit()

