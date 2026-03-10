from fastapi import APIRouter, Depends, Query, Body, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.chat import Conversation, ConversationParticipant, Message, MessageAttachment, MessageRead, ConversationStatus, ParticipantRole
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from app.utils.logger import logger
from pydantic import BaseModel, Field
from app.api.v1.websocket_chat import broadcast_new_message, broadcast_read_receipt

router = APIRouter()


class ParticipantInfo(BaseModel):
    userId: UUID
    userName: str
    userAvatar: Optional[str] = None
    isOnline: bool = False
    lastSeen: Optional[datetime] = None
    role: str = "participant"

    class Config:
        from_attributes = True


class LastMessageInfo(BaseModel):
    id: UUID
    content: str
    senderId: UUID
    timestamp: datetime
    isRead: bool

    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: UUID
    participants: List[ParticipantInfo]
    lastMessage: Optional[LastMessageInfo] = None
    unreadCount: int = 0
    updatedAt: datetime
    subject: Optional[str] = None

    class Config:
        from_attributes = True


class ConversationsListResponse(BaseModel):
    conversations: List[ConversationResponse]
    total: int
    limit: int
    offset: int


class MessageAttachmentResponse(BaseModel):
    id: UUID
    fileName: str
    fileUrl: str
    fileSize: int
    mimeType: str

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: UUID
    conversationId: UUID
    senderId: UUID
    senderName: str
    senderAvatar: Optional[str] = None
    content: str
    timestamp: datetime
    isRead: bool
    attachments: List[MessageAttachmentResponse] = []

    class Config:
        from_attributes = True


class MessagesListResponse(BaseModel):
    messages: List[MessageResponse]
    hasMore: bool
    total: int


class SendMessageRequest(BaseModel):
    content: str = Field(..., max_length=5000)
    attachments: Optional[List[UUID]] = None


class MarkReadRequest(BaseModel):
    messageIds: Optional[List[UUID]] = None


class CreateConversationRequest(BaseModel):
    participantIds: List[UUID] = Field(..., min_items=1, max_items=10)
    subject: Optional[str] = Field(None, max_length=200)
    initialMessage: Optional[str] = Field(None, max_length=5000)


class UpdateConversationRequest(BaseModel):
    subject: Optional[str] = Field(None, max_length=200)
    muted: Optional[bool] = None
    archived: Optional[bool] = None


@router.get("/conversations", response_model=ConversationsListResponse)
async def get_conversations(
    status: Optional[str] = Query("active", description="Filter by status: active, archived, all"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all conversations for the current user"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get conversations where user is a participant
    query = (
        select(Conversation)
        .join(ConversationParticipant)
        .where(ConversationParticipant.user_id == current_user.id)
    )
    
    if status == "active":
        query = query.where(Conversation.status == ConversationStatus.ACTIVE)
    elif status == "archived":
        query = query.where(Conversation.status == ConversationStatus.ARCHIVED)
    # "all" includes all statuses
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    query = query.order_by(desc(Conversation.updated_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    conversations = result.scalars().all()
    
    # Build response
    conversation_responses = []
    for conv in conversations:
        # Get participants
        participants_result = await db.execute(
            select(ConversationParticipant).where(ConversationParticipant.conversation_id == conv.id)
        )
        participants = participants_result.scalars().all()
        
        participant_infos = []
        for p in participants:
            user_result = await db.execute(select(User).where(User.id == p.user_id))
            user = user_result.scalar_one_or_none()
            if user:
                participant_infos.append(ParticipantInfo(
                    userId=p.user_id,
                    userName=f"{user.first_name} {user.last_name}".strip() or user.email,
                    userAvatar=None,  # Add avatar URL if available
                    isOnline=False,  # Implement online status tracking
                    lastSeen=None,  # Implement last seen tracking
                    role=p.role.value
                ))
        
        # Get last message
        last_message_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(desc(Message.timestamp))
            .limit(1)
        )
        last_message = last_message_result.scalar_one_or_none()
        
        last_message_info = None
        if last_message:
            # Check if read by current user
            read_result = await db.execute(
                select(MessageRead).where(
                    and_(
                        MessageRead.message_id == last_message.id,
                        MessageRead.user_id == current_user.id
                    )
                )
            )
            is_read = read_result.scalar_one_or_none() is not None
            
            last_message_info = LastMessageInfo(
                id=last_message.id,
                content=last_message.content[:100],  # Truncate for preview
                senderId=last_message.sender_id,
                timestamp=last_message.timestamp,
                isRead=is_read
            )
        
        # Get unread count
        unread_messages_result = await db.execute(
            select(func.count(Message.id))
            .select_from(Message)
            .outerjoin(
                MessageRead,
                and_(
                    MessageRead.message_id == Message.id,
                    MessageRead.user_id == current_user.id
                )
            )
            .where(
                and_(
                    Message.conversation_id == conv.id,
                    Message.sender_id != current_user.id,
                    MessageRead.id.is_(None)
                )
            )
        )
        unread_count = unread_messages_result.scalar() or 0
        
        conversation_responses.append(ConversationResponse(
            id=conv.id,
            participants=participant_infos,
            lastMessage=last_message_info,
            unreadCount=unread_count,
            updatedAt=conv.updated_at or conv.created_at,
            subject=conv.subject
        ))
    
    return ConversationsListResponse(
        conversations=conversation_responses,
        total=total,
        limit=limit,
        offset=offset
    )


@router.get("/conversations/{conversation_id}/messages", response_model=MessagesListResponse)
async def get_conversation_messages(
    conversation_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    before: Optional[str] = Query(None, description="ISO 8601 timestamp - get messages before this time"),
    after: Optional[str] = Query(None, description="ISO 8601 timestamp - get messages after this time"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get messages for a conversation"""
    # Verify user is participant
    participant_result = await db.execute(
        select(ConversationParticipant).where(
            and_(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == current_user.id
            )
        )
    )
    participant = participant_result.scalar_one_or_none()
    
    if not participant:
        raise ForbiddenException("User not part of this conversation")
    
    # Get conversation
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()
    
    if not conversation:
        raise NotFoundException("Conversation", str(conversation_id))
    
    # Build query
    query = select(Message).where(Message.conversation_id == conversation_id)
    
    if before:
        try:
            before_dt = datetime.fromisoformat(before.replace("Z", "+00:00"))
            query = query.where(Message.timestamp < before_dt)
        except ValueError:
            raise BadRequestException("Invalid before timestamp format")
    
    if after:
        try:
            after_dt = datetime.fromisoformat(after.replace("Z", "+00:00"))
            query = query.where(Message.timestamp > after_dt)
        except ValueError:
            raise BadRequestException("Invalid after timestamp format")
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply limit and order
    query = query.order_by(desc(Message.timestamp)).limit(limit + 1)
    result = await db.execute(query)
    messages = result.scalars().all()
    
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]
    
    # Build response
    message_responses = []
    for msg in reversed(messages):  # Reverse to show oldest first
        # Get sender info
        sender_result = await db.execute(select(User).where(User.id == msg.sender_id))
        sender = sender_result.scalar_one_or_none()
        sender_name = f"{sender.first_name} {sender.last_name}".strip() if sender else "Unknown"
        
        # Check if read by current user
        read_result = await db.execute(
            select(MessageRead).where(
                and_(
                    MessageRead.message_id == msg.id,
                    MessageRead.user_id == current_user.id
                )
            )
        )
        is_read = read_result.scalar_one_or_none() is not None
        
        # Get attachments
        attachments_result = await db.execute(
            select(MessageAttachment).where(MessageAttachment.message_id == msg.id)
        )
        attachments = attachments_result.scalars().all()
        
        message_responses.append(MessageResponse(
            id=msg.id,
            conversationId=msg.conversation_id,
            senderId=msg.sender_id,
            senderName=sender_name,
            senderAvatar=None,
            content=msg.content,
            timestamp=msg.timestamp,
            isRead=is_read,
            attachments=[MessageAttachmentResponse.model_validate(a) for a in attachments]
        ))
    
    return MessagesListResponse(
        messages=message_responses,
        hasMore=has_more,
        total=total
    )


@router.post("/conversations/{conversation_id}/messages", response_model=Dict[str, MessageResponse], status_code=status.HTTP_201_CREATED)
async def send_message(
    conversation_id: UUID,
    message_data: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Send a message in a conversation"""
    # Verify user is participant
    participant_result = await db.execute(
        select(ConversationParticipant).where(
            and_(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == current_user.id
            )
        )
    )
    participant = participant_result.scalar_one_or_none()
    
    if not participant:
        raise ForbiddenException("User not part of this conversation")
    
    # Get conversation
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()
    
    if not conversation:
        raise NotFoundException("Conversation", str(conversation_id))
    
    # Create message
    message = Message(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=message_data.content
    )
    
    db.add(message)
    await db.commit()
    await db.refresh(message)
    
    # Update conversation updated_at
    conversation.updated_at = datetime.utcnow()
    await db.commit()
    
    # Get sender info
    sender_name = f"{current_user.first_name} {current_user.last_name}".strip() or current_user.email
    
    # Get attachments
    attachments_result = await db.execute(
        select(MessageAttachment).where(MessageAttachment.message_id == message.id)
    )
    attachments = attachments_result.scalars().all()
    
    message_response = MessageResponse(
        id=message.id,
        conversationId=message.conversation_id,
        senderId=message.sender_id,
        senderName=sender_name,
        senderAvatar=None,
        content=message.content,
        timestamp=message.timestamp,
        isRead=False,
        attachments=[MessageAttachmentResponse.model_validate(a) for a in attachments]
    )
    
    logger.info(f"Message sent: {message.id} in conversation {conversation_id}")
    
    # Broadcast new message via WebSocket
    try:
        await broadcast_new_message(
            conversation_id=conversation_id,
            message_data={
                "message_id": str(message.id),
                "conversation_id": str(conversation_id),
                "sender_id": str(message.sender_id),
                "sender_name": sender_name,
                "content": message.content,
                "timestamp": message.timestamp.isoformat(),
                "attachments": [{"id": str(a.id), "type": a.file_type, "url": a.file_url} for a in attachments]
            },
            exclude_user_id=current_user.id
        )
    except Exception as e:
        logger.error(f"Error broadcasting new message via WebSocket: {e}")
        # Don't fail the request if WebSocket broadcast fails
    
    return {"message": message_response}


@router.put("/conversations/{conversation_id}/read", response_model=Dict[str, Any])
async def mark_messages_as_read(
    conversation_id: UUID,
    read_data: MarkReadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark messages as read"""
    # Verify user is participant
    participant_result = await db.execute(
        select(ConversationParticipant).where(
            and_(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == current_user.id
            )
        )
    )
    participant = participant_result.scalar_one_or_none()
    
    if not participant:
        raise ForbiddenException("User not part of this conversation")
    
    # Get conversation
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()
    
    if not conversation:
        raise NotFoundException("Conversation", str(conversation_id))
    
    if read_data.messageIds:
        # Mark specific messages as read
        query = select(Message).where(
            and_(
                Message.conversation_id == conversation_id,
                Message.id.in_(read_data.messageIds)
            )
        )
    else:
        # Mark all unread messages as read
        query = select(Message).where(
            and_(
                Message.conversation_id == conversation_id,
                Message.sender_id != current_user.id
            )
        ).outerjoin(
            MessageRead,
            and_(
                MessageRead.message_id == Message.id,
                MessageRead.user_id == current_user.id
            )
        ).where(MessageRead.id.is_(None))
    
    result = await db.execute(query)
    messages = result.scalars().all()
    
    updated_count = 0
    read_messages = []
    for msg in messages:
        # Check if already read
        existing_read = await db.execute(
            select(MessageRead).where(
                and_(
                    MessageRead.message_id == msg.id,
                    MessageRead.user_id == current_user.id
                )
            )
        )
        if not existing_read.scalar_one_or_none():
            read_record = MessageRead(
                message_id=msg.id,
                user_id=current_user.id
            )
            db.add(read_record)
            read_messages.append((msg.id, read_record.read_at))
            updated_count += 1
    
    await db.commit()
    
    # Update participant last_read_at
    participant.last_read_at = datetime.utcnow()
    await db.commit()
    
    # Broadcast read receipts via WebSocket
    try:
        for message_id, read_at in read_messages:
            await broadcast_read_receipt(
                conversation_id=conversation_id,
                message_id=message_id,
                user_id=current_user.id,
                read_at=read_at
            )
    except Exception as e:
        logger.error(f"Error broadcasting read receipts via WebSocket: {e}")
        # Don't fail the request if WebSocket broadcast fails
    
    return {
        "updated": updated_count,
        "message": "Messages marked as read"
    }


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    message_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a message"""
    message_result = await db.execute(
        select(Message).where(Message.id == message_id)
    )
    message = message_result.scalar_one_or_none()
    
    if not message:
        raise NotFoundException("Message", str(message_id))
    
    # Only sender can delete
    if message.sender_id != current_user.id:
        raise ForbiddenException("User not authorized to delete this message")
    
    # Soft delete
    message.deleted_at = datetime.utcnow()
    await db.commit()
    
    logger.info(f"Message deleted: {message_id}")
    return None


@router.get("/conversations/{conversation_id}/participants", response_model=Dict[str, List[ParticipantInfo]])
async def get_conversation_participants(
    conversation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get conversation participants"""
    # Verify user is participant
    participant_result = await db.execute(
        select(ConversationParticipant).where(
            and_(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == current_user.id
            )
        )
    )
    if not participant_result.scalar_one_or_none():
        raise ForbiddenException("User not part of this conversation")
    
    # Get all participants
    participants_result = await db.execute(
        select(ConversationParticipant).where(ConversationParticipant.conversation_id == conversation_id)
    )
    participants = participants_result.scalars().all()
    
    participant_infos = []
    for p in participants:
        user_result = await db.execute(select(User).where(User.id == p.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            participant_infos.append(ParticipantInfo(
                userId=p.user_id,
                userName=f"{user.first_name} {user.last_name}".strip() or user.email,
                userAvatar=None,
                isOnline=False,
                lastSeen=p.last_read_at,
                role=p.role.value
            ))
    
    return {"participants": participant_infos}


@router.post("/conversations", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_conversation(
    conversation_data: CreateConversationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new conversation"""
    # Ensure current user is in participants
    if current_user.id not in conversation_data.participantIds:
        conversation_data.participantIds.append(current_user.id)
    
    # Remove duplicates
    participant_ids = list(set(conversation_data.participantIds))
    
    if len(participant_ids) < 1:
        raise BadRequestException("At least one participant is required")
    
    if len(participant_ids) > 10:
        raise BadRequestException("Maximum 10 participants allowed")
    
    # Verify all participants exist
    users_result = await db.execute(
        select(User).where(User.id.in_(participant_ids))
    )
    users = users_result.scalars().all()
    
    if len(users) != len(participant_ids):
        raise NotFoundException("User", "One or more participant IDs not found")
    
    # Create conversation
    conversation = Conversation(
        subject=conversation_data.subject,
        status=ConversationStatus.ACTIVE
    )
    
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    
    # Add participants
    for user_id in participant_ids:
        role = ParticipantRole.ADMIN if user_id == current_user.id else ParticipantRole.PARTICIPANT
        participant = ConversationParticipant(
            conversation_id=conversation.id,
            user_id=user_id,
            role=role
        )
        db.add(participant)
    
    await db.commit()
    
    # Create initial message if provided
    initial_message = None
    if conversation_data.initialMessage:
        message = Message(
            conversation_id=conversation.id,
            sender_id=current_user.id,
            content=conversation_data.initialMessage
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        initial_message = {
            "id": str(message.id),
            "content": message.content,
            "timestamp": message.timestamp.isoformat()
        }
    
    # Build response
    participants_result = await db.execute(
        select(ConversationParticipant).where(ConversationParticipant.conversation_id == conversation.id)
    )
    participants = participants_result.scalars().all()
    
    participant_infos = []
    for p in participants:
        user_result = await db.execute(select(User).where(User.id == p.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            participant_infos.append(ParticipantInfo(
                userId=p.user_id,
                userName=f"{user.first_name} {user.last_name}".strip() or user.email,
                userAvatar=None,
                isOnline=False,
                lastSeen=None,
                role=p.role.value
            ))
    
    response = {
        "conversation": {
            "id": conversation.id,
            "participants": [p.model_dump() for p in participant_infos],
            "subject": conversation.subject,
            "createdAt": conversation.created_at.isoformat(),
            "lastMessage": None,
            "unreadCount": 0
        }
    }
    
    if initial_message:
        response["initialMessage"] = initial_message
    
    logger.info(f"Conversation created: {conversation.id}")
    return response


@router.put("/conversations/{conversation_id}", response_model=Dict[str, Any])
async def update_conversation(
    conversation_id: UUID,
    update_data: UpdateConversationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update conversation (mute, archive, etc.)"""
    # Verify user is participant
    participant_result = await db.execute(
        select(ConversationParticipant).where(
            and_(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == current_user.id
            )
        )
    )
    participant = participant_result.scalar_one_or_none()
    
    if not participant:
        raise ForbiddenException("User not part of this conversation")
    
    # Get conversation
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()
    
    if not conversation:
        raise NotFoundException("Conversation", str(conversation_id))
    
    # Update fields
    if update_data.subject is not None:
        conversation.subject = update_data.subject
    
    if update_data.archived is not None:
        if update_data.archived:
            conversation.status = ConversationStatus.ARCHIVED
            conversation.archived_at = datetime.utcnow()
        else:
            conversation.status = ConversationStatus.ACTIVE
            conversation.archived_at = None
    
    if update_data.muted is not None:
        participant.is_muted = update_data.muted
    
    await db.commit()
    await db.refresh(conversation)
    
    return {
        "conversation": {
            "id": conversation.id,
            "subject": conversation.subject,
            "muted": participant.is_muted,
            "archived": conversation.status == ConversationStatus.ARCHIVED,
            "updatedAt": conversation.updated_at.isoformat()
        }
    }
