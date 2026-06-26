"""WebSocket endpoint for real-time user notifications.

Connection:  wss://<host>/api/v1/ws/notifications?token=<JWT_ACCESS_TOKEN>

Auth: the browser WebSocket API can't set headers, so the JWT is passed as the
`token` query param and validated on accept. Invalid/expired tokens are rejected
with close code 4401 so the client can refresh and reconnect.

Server pushes (see app/services/appraisal_notifications.py):
    { "type": "appraisal_message", "notification_id": ..., "appraisal_id": ...,
      "asset_code": ..., "asset_name": ..., "author_kind": ..., "author_name": ...,
      "preview": ..., "created_at": ... }

Keepalive: the server sends {"type":"ping"} every ~30s; clients may also send
{"type":"ping"} and will receive {"type":"pong"}.
"""
import asyncio
from typing import Optional
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect, Query

from app.database import AsyncSessionLocal
from app.core.websocket_manager import manager, get_user_from_token
from app.models.user import User
from app.utils.logger import logger

PING_INTERVAL_SECONDS = 30
WS_AUTH_FAILED_CODE = 4401  # client refreshes token + reconnects on this code


async def _heartbeat(websocket: WebSocket):
    """Send a periodic ping so Railway's proxy doesn't drop the idle socket."""
    try:
        while True:
            await asyncio.sleep(PING_INTERVAL_SECONDS)
            await websocket.send_json({"type": "ping"})
    except asyncio.CancelledError:
        pass
    except Exception:
        # Socket is gone; the main loop will handle teardown.
        pass


async def websocket_notifications_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
):
    user: Optional[User] = None
    heartbeat_task: Optional[asyncio.Task] = None

    # Authenticate BEFORE accepting the connection meaningfully.
    db = AsyncSessionLocal()
    try:
        try:
            user = await get_user_from_token(token, db)
        except Exception as e:
            logger.warning(f"Notifications WS auth error: {e}")
            user = None
    finally:
        await db.close()

    if not user:
        # Must accept before we can send a close code the browser can read.
        await websocket.accept()
        await websocket.close(code=WS_AUTH_FAILED_CODE, reason="Invalid or expired token")
        return

    await manager.connect(websocket, user.id)
    await manager.send_personal_message(websocket, {
        "type": "connected",
        "user_id": str(user.id),
    })

    heartbeat_task = asyncio.create_task(_heartbeat(websocket))
    try:
        while True:
            data = await websocket.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                await manager.send_personal_message(websocket, {"type": "pong"})
            # Other inbound messages are ignored; this channel is push-only.
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Notifications WS error for user {user.id}: {e}")
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
        await manager.disconnect(websocket, user.id)
