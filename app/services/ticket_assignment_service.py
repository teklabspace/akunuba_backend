from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.support import SupportTicket
from app.models.user import User
from app.core.permissions import Role, Permission, has_permission
from app.utils.logger import logger


class TicketAssignmentService:
    @staticmethod
    async def auto_assign_ticket(db: AsyncSession, ticket: SupportTicket):
        """Auto-assign ticket using round-robin"""
        # Find all users with support permissions
        support_users_result = await db.execute(
            select(User).where(
                User.is_active == True,
                User.role.in_([Role.ADMIN, Role.ADVISOR])
            )
        )
        support_users = support_users_result.scalars().all()
        
        if not support_users:
            logger.warning("No support users found for auto-assignment")
            return
        
        # Get ticket counts per user
        user_loads = {}
        for user in support_users:
            count_result = await db.execute(
                select(func.count(SupportTicket.id)).where(
                    SupportTicket.assigned_to == user.id,
                    SupportTicket.status.in_(["open", "in_progress"])
                )
            )
            user_loads[user.id] = count_result.scalar() or 0
        
        # Assign to user with least tickets
        if user_loads:
            assigned_user_id = min(user_loads, key=user_loads.get)
            ticket.assigned_to = assigned_user_id
            logger.info(f"Auto-assigned ticket {ticket.id} to user {assigned_user_id}")
        else:
            # Round-robin: assign to first available user
            ticket.assigned_to = support_users[0].id
            logger.info(f"Auto-assigned ticket {ticket.id} to user {support_users[0].id}")

