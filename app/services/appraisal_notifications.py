"""Persist + real-time push of appraisal notifications.

Two event types, both delivered to the bell (persisted Notification rows) and
live over WebSocket:

- "appraisal_created": an investor requests a human (non-AI) appraisal.
  Recipients: all active staff (admins + advisors). The "view" button on the
  notification deep-links via appraisal_id.
- "appraisal_message": a new comment/message on an appraisal.
    investor author -> all active staff
    staff/system author (client-visible only) -> the owning investor

Each notification carries the appraisal_id + asset_code + author + preview so the
frontend can show a popup and deep-link to the thread.

Note on "assigned advisor": there is currently no per-appraisal assignment field
(assignment is only recorded in free-text notes), so staff events fan out to ALL
admins + advisors. Add an `assigned_to` column to target a single advisor.
"""
import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Role
from app.core.websocket_manager import manager
from app.models.account import Account
from app.models.asset import Asset, AssetAppraisal, AppraisalComment
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services import appraisal_thread
from app.utils.logger import logger

PREVIEW_LEN = 120


def _preview(body: str) -> str:
    return (body or "").strip()[:PREVIEW_LEN]


async def _owner_user_id(db: AsyncSession, asset: Asset) -> Optional[UUID]:
    return (await db.execute(
        select(Account.user_id).where(Account.id == asset.account_id)
    )).scalar_one_or_none()


async def _active_staff(db: AsyncSession) -> List[User]:
    return (await db.execute(
        select(User).where(and_(
            User.role.in_([Role.ADMIN, Role.ADVISOR]),
            User.is_active.is_(True),
        ))
    )).scalars().all()


async def _account_id_for(db: AsyncSession, user_id: UUID) -> Optional[UUID]:
    return (await db.execute(
        select(Account.id).where(Account.user_id == user_id)
    )).scalar_one_or_none()


async def _persist_and_push(
    db: AsyncSession,
    *,
    recipients: List[Tuple[UUID, str]],   # (user_id, author_name_for_recipient)
    event_type: str,                       # "appraisal_message" | "appraisal_created"
    appraisal: AssetAppraisal,
    asset: Asset,
    author_kind: str,
    title: str,
    preview: str,
    created_iso: Optional[str],
    send_email: bool = False,
) -> None:
    if not recipients:
        return

    notifs = []
    for user_id, author_name in recipients:
        meta = {
            "type": event_type,
            "appraisal_id": str(appraisal.id),
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "asset_name": asset.name,
            "appraisal_type": appraisal.appraisal_type.value if appraisal.appraisal_type else None,
            "author_kind": author_kind,
            "author_name": author_name,
            "preview": preview,
        }
        notif = Notification(
            user_id=user_id,
            account_id=await _account_id_for(db, user_id),
            notification_type=NotificationType.APPRAISAL_MESSAGE,  # coarse DB category
            title=title,
            message=preview,
            meta_data=json.dumps(meta),
        )
        db.add(notif)
        notifs.append((notif, user_id, author_name))

    await db.commit()

    for notif, user_id, author_name in notifs:
        await db.refresh(notif)
        await manager.send_to_user(user_id, {
            "type": event_type,
            "notification_id": str(notif.id),
            "appraisal_id": str(appraisal.id),
            "asset_code": asset.asset_code,
            "asset_name": asset.name,
            "appraisal_type": appraisal.appraisal_type.value if appraisal.appraisal_type else None,
            "author_kind": author_kind,
            "author_name": author_name,
            "preview": preview,
            "created_at": created_iso or (notif.created_at.isoformat() if notif.created_at else None),
        })

    if send_email:
        from app.services.email_service import EmailService

        user_ids = [user_id for _, user_id, _ in notifs]
        users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        users_by_id = {u.id: u for u in users}
        emailed = False
        for notif, user_id, _ in notifs:
            recipient = users_by_id.get(user_id)
            if not recipient or not recipient.email:
                continue
            to_name = f"{recipient.first_name or ''} {recipient.last_name or ''}".strip() or "User"
            sent = await EmailService.send_notification_email(
                to_email=recipient.email,
                to_name=to_name,
                notification_title=notif.title,
                notification_message=notif.message,
                notification_type=notif.notification_type.value,
            )
            if sent:
                notif.email_sent = True
                notif.email_sent_at = datetime.now(timezone.utc)
                emailed = True
        if emailed:
            await db.commit()

    logger.info(f"Dispatched {event_type} for appraisal {appraisal.id} to {len(notifs)} user(s)")


async def dispatch_appraisal_created(
    db: AsyncSession,
    appraisal: AssetAppraisal,
    asset: Asset,
    author: User,
) -> None:
    """Investor requested a human appraisal -> notify all active staff."""
    try:
        author_name = appraisal_thread.display_author_name(author, "investor", for_investor=False)
        recipients = [(s.id, author_name) for s in await _active_staff(db) if s.id != author.id]
        atype = appraisal.appraisal_type.value if appraisal.appraisal_type else "appraisal"
        await _persist_and_push(
            db,
            recipients=recipients,
            event_type="appraisal_created",
            appraisal=appraisal,
            asset=asset,
            author_kind="investor",
            title=f"New {atype} appraisal request on {asset.asset_code or asset.name}",
            preview=f"{author_name} requested a {atype} appraisal for {asset.name}.",
            created_iso=appraisal.requested_at.isoformat() if appraisal.requested_at else None,
        )
    except Exception as e:  # noqa: BLE001 — never break the request path
        logger.error(f"Failed to dispatch appraisal_created notification: {e}", exc_info=True)


async def dispatch_appraisal_message(
    db: AsyncSession,
    appraisal: AssetAppraisal,
    asset: Asset,
    comment: AppraisalComment,
    author: User,
) -> None:
    """New appraisal comment -> notify the counterpart(s)."""
    try:
        kind = appraisal_thread.author_kind(comment.author_role, comment.comment_type)

        recipients: List[Tuple[UUID, str]] = []
        if kind == "investor":
            author_name = appraisal_thread.display_author_name(author, "investor", for_investor=False)
            recipients = [(s.id, author_name) for s in await _active_staff(db) if s.id != author.id]
        else:
            # Staff/system: only client-visible comments reach the investor.
            if getattr(comment, "is_internal", False):
                return
            owner_id = await _owner_user_id(db, asset)
            if owner_id and owner_id != author.id:
                author_name = appraisal_thread.display_author_name(author, comment.author_role, for_investor=True)
                recipients = [(owner_id, author_name)]

        await _persist_and_push(
            db,
            recipients=recipients,
            event_type="appraisal_message",
            appraisal=appraisal,
            asset=asset,
            author_kind=kind,
            title=f"New message on {asset.asset_code or 'appraisal'}",
            preview=_preview(comment.body),
            created_iso=comment.created_at.isoformat() if comment.created_at else None,
            # Staff replies email the asset owner; investor messages stay
            # bell-only for staff (avoid mailing every admin/advisor).
            send_email=(kind != "investor"),
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to dispatch appraisal_message notification: {e}", exc_info=True)
