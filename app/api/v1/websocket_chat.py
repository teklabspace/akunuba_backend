"""
WebSocket API for Real-Time Chat

This module provides WebSocket endpoints for real-time chat functionality,
including message delivery, typing indicators, and presence updates.
"""
import json
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from app.database import AsyncSessionLocal
from app.core.websocket_manager import (
    manager,
    get_user_from_token,
    verify_conversation_access
)
from app.models.chat import Conversation, Message, MessageRead
from app.models.user import User
from app.utils.logger import logger
from pydantic import BaseModel, ValidationError

router = APIRouter()


class WebSocketMessage(BaseModel):
    """Base model for WebSocket message payloads"""
    type: str
    conversation_id: Optional[str] = None
    data: Optional[dict] = None


# WebSocket endpoint (will be registered directly on app in main.py)
async def websocket_chat_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token")
):
    """
    WebSocket endpoint for real-time chat.
    
    Connection: wss://your-api-domain/ws/chat?token=<JWT_ACCESS_TOKEN>
    
    Events:
    - message:new - New message received
    - message:read - Message read receipt
    - typing:start - User started typing
    - typing:stop - User stopped typing
    - presence:update - User online/offline status
    - error - Error message
    
    Client can send:
    - {"type": "join", "conversation_id": "uuid"} - Join a conversation
    - {"type": "typing:start", "conversation_id": "uuid"} - Start typing
    - {"type": "typing:stop", "conversation_id": "uuid"} - Stop typing
    - {"type": "mark:read", "conversation_id": "uuid", "message_id": "uuid"} - Mark message as read
    """
    user: Optional[User] = None
    db: Optional[AsyncSession] = None
    
    try:
        # Create database session (WebSocket endpoints can't use Depends)
        db = AsyncSessionLocal()
        
        try:
            # Authenticate user
            user = await get_user_from_token(token, db)
        except Exception as e:
            logger.warning(f"WebSocket auth failed: {e}")
            await websocket.close(code=1008, reason="Invalid authentication token")
            return

        if not user:
            await websocket.close(code=1008, reason="Invalid authentication token")
            return
        
        # Connect user
        await manager.connect(websocket, user.id)
        
        # Send welcome message
        await manager.send_personal_message(websocket, {
            "type": "connected",
            "user_id": str(user.id),
            "message": "WebSocket connection established"
        })
        
        # Main message loop
        while True:
            try:
                # Receive message from client
                data = await websocket.receive_json()
                
                # Validate message format
                try:
                    message = WebSocketMessage(**data)
                except ValidationError as e:
                    await manager.send_personal_message(websocket, {
                        "type": "error",
                        "message": f"Invalid message format: {e.errors()}"
                    })
                    continue
                
                # Handle different message types
                if message.type == "join":
                    await handle_join_conversation(
                        websocket, user.id, message.conversation_id, db
                    )
                
                elif message.type == "typing:start":
                    await handle_typing_start(
                        websocket, user.id, message.conversation_id
                    )
                
                elif message.type == "typing:stop":
                    await handle_typing_stop(
                        websocket, user.id, message.conversation_id
                    )
                
                elif message.type == "mark:read":
                    await handle_mark_read(
                        websocket, user.id, message.conversation_id,
                        message.data.get("message_id") if message.data else None,
                        db
                    )
        
        finally:
            # Close database session
            if db:
                await db.close()
                
                else:
                    await manager.send_personal_message(websocket, {
                        "type": "error",
                        "message": f"Unknown message type: {message.type}"
                    })
            
            except json.JSONDecodeError:
                await manager.send_personal_message(websocket, {
                    "type": "error",
                    "message": "Invalid JSON format"
                })
            
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
                await manager.send_personal_message(websocket, {
                    "type": "error",
                    "message": "Internal server error"
                })
    
    except WebSocketDisconnect:
        if user:
            await manager.disconnect(websocket, user.id)
        logger.info(f"WebSocket disconnected for user {user.id if user else 'unknown'}")
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if user:
            await manager.disconnect(websocket, user.id)
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except:
            pass


async def handle_join_conversation(
    websocket: WebSocket,
    user_id: UUID,
    conversation_id_str: Optional[str],
    db: AsyncSession
):
    """Handle user joining a conversation"""
    if not conversation_id_str:
        await manager.send_personal_message(websocket, {
            "type": "error",
            "message": "conversation_id is required"
        })
        return
    
    try:
        conversation_id = UUID(conversation_id_str)
    except ValueError:
        await manager.send_personal_message(websocket, {
            "type": "error",
            "message": "Invalid conversation_id format"
        })
        return
    
    # Verify user has access to conversation
    has_access = await verify_conversation_access(user_id, conversation_id, db)
    if not has_access:
        await manager.send_personal_message(websocket, {
            "type": "error",
            "message": "Access denied to this conversation"
        })
        return
    
    # Join conversation room
    await manager.join_conversation(user_id, conversation_id)
    
    await manager.send_personal_message(websocket, {
        "type": "joined",
        "conversation_id": conversation_id_str,
        "message": f"Joined conversation {conversation_id_str}"
    })


async def handle_typing_start(
    websocket: WebSocket,
    user_id: UUID,
    conversation_id_str: Optional[str]
):
    """Handle typing start event"""
    if not conversation_id_str:
        return
    
    try:
        conversation_id = UUID(conversation_id_str)
        await manager.set_typing(conversation_id, user_id, is_typing=True)
    except ValueError:
        pass


async def handle_typing_stop(
    websocket: WebSocket,
    user_id: UUID,
    conversation_id_str: Optional[str]
):
    """Handle typing stop event"""
    if not conversation_id_str:
        return
    
    try:
        conversation_id = UUID(conversation_id_str)
        await manager.set_typing(conversation_id, user_id, is_typing=False)
    except ValueError:
        pass


async def handle_mark_read(
    websocket: WebSocket,
    user_id: UUID,
    conversation_id_str: Optional[str],
    message_id_str: Optional[str],
    db: AsyncSession
):
    """Handle mark message as read"""
    if not conversation_id_str:
        await manager.send_personal_message(websocket, {
            "type": "error",
            "message": "conversation_id is required"
        })
        return
    
    try:
        conversation_id = UUID(conversation_id_str)
    except ValueError:
        await manager.send_personal_message(websocket, {
            "type": "error",
            "message": "Invalid conversation_id format"
        })
        return
    
    # Verify access
    has_access = await verify_conversation_access(user_id, conversation_id, db)
    if not has_access:
        await manager.send_personal_message(websocket, {
            "type": "error",
            "message": "Access denied to this conversation"
        })
        return
    
    # If message_id provided, mark specific message as read
    if message_id_str:
        try:
            message_id = UUID(message_id_str)
            # Check if read receipt already exists
            result = await db.execute(
                select(MessageRead).where(
                    MessageRead.message_id == message_id,
                    MessageRead.user_id == user_id
                )
            )
            read_receipt = result.scalar_one_or_none()
            
            if not read_receipt:
                # Create read receipt
                read_receipt = MessageRead(
                    message_id=message_id,
                    user_id=user_id,
                    read_at=datetime.utcnow()
                )
                db.add(read_receipt)
                await db.commit()
            
            # Broadcast read receipt
            await manager.broadcast_to_conversation(
                conversation_id=conversation_id,
                event_type="message:read",
                data={
                    "message_id": message_id_str,
                    "user_id": str(user_id),
                    "read_at": read_receipt.read_at.isoformat()
                },
                exclude_user_id=user_id
            )
        except ValueError:
            pass
    else:
        # Mark all unread messages in conversation as read
        # This would require a more complex query - for now, just acknowledge
        await manager.send_personal_message(websocket, {
            "type": "read:acknowledged",
            "conversation_id": conversation_id_str
        })


# Function to send new message event via WebSocket
async def broadcast_new_message(
    conversation_id: UUID,
    message_data: dict,
    exclude_user_id: Optional[UUID] = None
):
    """
    Broadcast a new message to all users in a conversation.
    This is called from the REST API when a new message is created.
    """
    await manager.broadcast_to_conversation(
        conversation_id=conversation_id,
        event_type="message:new",
        data=message_data,
        exclude_user_id=exclude_user_id
    )


# Function to send read receipt via WebSocket
async def broadcast_read_receipt(
    conversation_id: UUID,
    message_id: UUID,
    user_id: UUID,
    read_at: datetime
):
    """Broadcast read receipt to all users in a conversation"""
    await manager.broadcast_to_conversation(
        conversation_id=conversation_id,
        event_type="message:read",
        data={
            "message_id": str(message_id),
            "user_id": str(user_id),
            "read_at": read_at.isoformat()
        },
        exclude_user_id=user_id
    )
