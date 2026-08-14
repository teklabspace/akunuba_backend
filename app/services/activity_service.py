"""Write path for the platform activity / audit log.

The single rule here: **logging must never break the operation being logged.**
An audit write that raises would turn a successful read into a 500, so every
failure is swallowed and reported to the application logger instead.
"""
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityLog

logger = logging.getLogger(__name__)


class ActivityService:
    @staticmethod
    async def log(
        db: AsyncSession,
        actor_id: Optional[UUID],
        subject_user_id: Optional[UUID],
        action: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[UUID] = None,
        summary: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append one row. Never raises."""
        try:
            db.add(ActivityLog(
                actor_id=actor_id,
                subject_user_id=subject_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                summary=summary,
                meta_data=meta,
            ))
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - audit must not break the caller
            logger.warning(f"activity log write failed for action={action}: {exc}")
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass


# Module-level convenience alias so call sites read as one short line.
log_activity = ActivityService.log
