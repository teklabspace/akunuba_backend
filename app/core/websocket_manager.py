"""
WebSocket Connection Manager with Redis Pub/Sub Support

This module manages WebSocket connections for real-time chat features.
It uses Redis pub/sub to enable multi-instance deployments where messages
can be broadcast across different server instances.
"""
import json
import asyncio
from typing import Dict, Set, Optional
from uuid import UUID
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.core.security import decode_access_token
from app.models.user import User
from app.models.chat import Conversation, ConversationParticipant
from app.utils.logger import logger
import redis.asyncio as redis
from contextlib import asynccontextmanager


# Redis channel for user-targeted notifications (fan-out across workers/replicas).
USER_NOTIFICATIONS_CHANNEL = "notifications:user"


class ConnectionManager:
    """
    Manages WebSocket connections and Redis pub/sub for real-time messaging.
    
    Features:
    - Per-user connection tracking
    - Per-conversation room management
    - Redis pub/sub for multi-instance support
    - Typing indicators
    - Presence tracking (online/offline)
    """
    
    def __init__(self):
        # Active connections: {user_id: Set[WebSocket]}
        self.active_connections: Dict[UUID, Set[WebSocket]] = {}
        # Conversation rooms: {conversation_id: Set[user_id]}
        self.conversation_rooms: Dict[UUID, Set[UUID]] = {}
        # Typing indicators: {conversation_id: {user_id: timestamp}}
        self.typing_users: Dict[UUID, Dict[UUID, float]] = {}
        # Redis connection pool
        self.redis_client: Optional[redis.Redis] = None
        self.redis_pubsub: Optional[redis.client.PubSub] = None
        self._redis_task: Optional[asyncio.Task] = None
        
    async def connect_redis(self):
        """Initialize Redis connection and pub/sub"""
        try:
            # Never block app startup on Redis connectivity (common local-dev pain).
            async def _connect():
                client = redis.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await client.ping()
                return client

            self.redis_client = await asyncio.wait_for(_connect(), timeout=5.0)
            self.redis_pubsub = self.redis_client.pubsub()
            # Always-on subscription so user-targeted notifications fan out across
            # workers/replicas the moment they're published.
            await self.redis_pubsub.subscribe(USER_NOTIFICATIONS_CHANNEL)
            logger.info("[OK] Redis connected for WebSocket pub/sub")

            # Start listening to Redis messages
            self._redis_task = asyncio.create_task(self._listen_redis())
        except asyncio.TimeoutError:
            logger.warning("[WARN] Redis connection timed out during startup; continuing without Redis pub/sub")
            logger.warning("   WebSocket will work in single-instance mode only")
            self.redis_client = None
            self.redis_pubsub = None
        except Exception as e:
            logger.warning(f"[WARN] Redis connection failed: {e}")
            logger.warning("   WebSocket will work in single-instance mode only")
            self.redis_client = None
            self.redis_pubsub = None
    
    async def disconnect_redis(self):
        """Close Redis connection"""
        if self._redis_task:
            self._redis_task.cancel()
            try:
                await self._redis_task
            except asyncio.CancelledError:
                pass
        
        if self.redis_pubsub:
            await self.redis_pubsub.unsubscribe()
            await self.redis_pubsub.close()
        
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")
    
    async def _listen_redis(self):
        """Listen to Redis pub/sub messages and broadcast to local connections"""
        if not self.redis_pubsub:
            return
        
        try:
            async for message in self.redis_pubsub.listen():
                if message["type"] == "message":
                    try:
                        # User-targeted notification fan-out (this worker delivers
                        # to its own local sockets for the target user).
                        if message.get("channel") == USER_NOTIFICATIONS_CHANNEL:
                            envelope = json.loads(message["data"])
                            target_user_id = UUID(envelope["target_user_id"])
                            await self._send_to_user_local(target_user_id, envelope["payload"])
                            continue

                        data = json.loads(message["data"])
                        event_type = data.get("type")
                        conversation_id = UUID(data.get("conversation_id"))
                        user_id = UUID(data.get("user_id"))

                        # Broadcast to local connections in this conversation
                        await self._broadcast_to_conversation_local(
                            conversation_id=conversation_id,
                            event_type=event_type,
                            data=data,
                            exclude_user_id=user_id  # Don't echo back to sender
                        )
                    except Exception as e:
                        logger.error(f"Error processing Redis message: {e}")
        except asyncio.CancelledError:
            logger.info("Redis listener task cancelled")
        except Exception as e:
            logger.error(f"Redis listener error: {e}")
    
    async def _publish_to_redis(self, conversation_id: UUID, event_type: str, data: dict):
        """Publish event to Redis pub/sub"""
        if not self.redis_client:
            return
        
        try:
            channel = f"chat:conversation:{conversation_id}"
            message = {
                "type": event_type,
                "conversation_id": str(conversation_id),
                "user_id": data.get("user_id"),
                **data
            }
            await self.redis_client.publish(channel, json.dumps(message))
        except Exception as e:
            logger.error(f"Error publishing to Redis: {e}")
    
    async def connect(self, websocket: WebSocket, user_id: UUID):
        """Accept WebSocket connection and register user"""
        await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        
        self.active_connections[user_id].add(websocket)
        logger.info(f"User {user_id} connected. Total connections: {len(self.active_connections[user_id])}")
        
        # Subscribe to Redis for user's conversations
        if self.redis_pubsub:
            # We'll subscribe to conversations when user joins them
            pass
    
    async def disconnect(self, websocket: WebSocket, user_id: UUID):
        """Remove WebSocket connection"""
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        
        # Remove from all conversation rooms
        for conversation_id in list(self.conversation_rooms.keys()):
            if user_id in self.conversation_rooms[conversation_id]:
                self.conversation_rooms[conversation_id].discard(user_id)
                if not self.conversation_rooms[conversation_id]:
                    del self.conversation_rooms[conversation_id]
        
        logger.info(f"User {user_id} disconnected")
    
    async def join_conversation(self, user_id: UUID, conversation_id: UUID):
        """Add user to a conversation room"""
        if conversation_id not in self.conversation_rooms:
            self.conversation_rooms[conversation_id] = set()
        
        self.conversation_rooms[conversation_id].add(user_id)
        
        # Subscribe to Redis channel for this conversation
        if self.redis_pubsub:
            channel = f"chat:conversation:{conversation_id}"
            await self.redis_pubsub.subscribe(channel)
    
    async def leave_conversation(self, user_id: UUID, conversation_id: UUID):
        """Remove user from a conversation room"""
        if conversation_id in self.conversation_rooms:
            self.conversation_rooms[conversation_id].discard(user_id)
            if not self.conversation_rooms[conversation_id]:
                del self.conversation_rooms[conversation_id]
    
    async def send_personal_message(self, websocket: WebSocket, message: dict):
        """Send message to a specific WebSocket connection"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")

    async def send_to_user(self, user_id: UUID, message: dict):
        """Deliver a message to every active socket of a single user.

        With Redis available, publishes to the user-notifications channel so all
        workers/replicas deliver to their own local sockets (exactly once each).
        Without Redis, delivers to this process's local sockets directly.
        """
        if self.redis_client:
            try:
                await self.redis_client.publish(
                    USER_NOTIFICATIONS_CHANNEL,
                    json.dumps({"target_user_id": str(user_id), "payload": message}),
                )
                return
            except Exception as e:
                logger.error(f"Error publishing user notification to Redis: {e}")
                # Fall through to local delivery so the sending worker still notifies.
        await self._send_to_user_local(user_id, message)

    async def _send_to_user_local(self, user_id: UUID, message: dict):
        """Send a message to a user's sockets on THIS process only."""
        sockets = self.active_connections.get(user_id)
        if not sockets:
            return
        dead = []
        for websocket in list(sockets):
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to user {user_id}: {e}")
                dead.append(websocket)
        for websocket in dead:
            await self.disconnect(websocket, user_id)
    
    async def broadcast_to_conversation(
        self,
        conversation_id: UUID,
        event_type: str,
        data: dict,
        exclude_user_id: Optional[UUID] = None
    ):
        """
        Broadcast event to all users in a conversation.
        Publishes to Redis for multi-instance support.
        """
        # Publish to Redis first (for other instances)
        await self._publish_to_redis(conversation_id, event_type, data)
        
        # Broadcast to local connections
        await self._broadcast_to_conversation_local(
            conversation_id, event_type, data, exclude_user_id
        )
    
    async def _broadcast_to_conversation_local(
        self,
        conversation_id: UUID,
        event_type: str,
        data: dict,
        exclude_user_id: Optional[UUID] = None
    ):
        """Broadcast to local WebSocket connections only"""
        if conversation_id not in self.conversation_rooms:
            return
        
        message = {
            "type": event_type,
            "conversation_id": str(conversation_id),
            **data
        }
        
        # Send to all users in the conversation room
        disconnected_users = []
        for user_id in self.conversation_rooms[conversation_id]:
            if exclude_user_id and user_id == exclude_user_id:
                continue
            
            if user_id in self.active_connections:
                for websocket in self.active_connections[user_id]:
                    try:
                        await websocket.send_json(message)
                    except Exception as e:
                        logger.error(f"Error broadcasting to user {user_id}: {e}")
                        disconnected_users.append((user_id, websocket))
        
        # Clean up disconnected connections
        for user_id, websocket in disconnected_users:
            await self.disconnect(websocket, user_id)
    
    def is_user_online(self, user_id: UUID) -> bool:
        """Check if user has active WebSocket connections"""
        return user_id in self.active_connections and len(self.active_connections[user_id]) > 0
    
    async def set_typing(
        self,
        conversation_id: UUID,
        user_id: UUID,
        is_typing: bool
    ):
        """Update typing indicator for a user in a conversation"""
        if conversation_id not in self.typing_users:
            self.typing_users[conversation_id] = {}
        
        if is_typing:
            import time
            self.typing_users[conversation_id][user_id] = time.time()
        else:
            self.typing_users[conversation_id].pop(user_id, None)
        
        # Broadcast typing event
        await self.broadcast_to_conversation(
            conversation_id=conversation_id,
            event_type="typing:update",
            data={
                "user_id": str(user_id),
                "is_typing": is_typing
            },
            exclude_user_id=user_id
        )


# Global connection manager instance
manager = ConnectionManager()


async def get_user_from_token(token: str, db: AsyncSession) -> Optional[User]:
    """Validate JWT token and return user"""
    payload = decode_access_token(token)
    if not payload:
        return None
    
    user_id = payload.get("sub")
    if not user_id:
        return None
    
    try:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
    except Exception as e:
        logger.error(f"Error fetching user from token: {e}")
    
    return None


async def verify_conversation_access(
    user_id: UUID,
    conversation_id: UUID,
    db: AsyncSession
) -> bool:
    """Verify that user has access to the conversation"""
    try:
        result = await db.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user_id
            )
        )
        participant = result.scalar_one_or_none()
        return participant is not None
    except Exception as e:
        logger.error(f"Error verifying conversation access: {e}")
        return False
