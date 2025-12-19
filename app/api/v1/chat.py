from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.integrations.sendbird_client import SendbirdClient
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from app.api.deps import get_account, get_user_subscription_plan
from app.core.features import Feature, has_feature
from app.utils.logger import logger
from pydantic import BaseModel

router = APIRouter()


class CreateChannelRequest(BaseModel):
    channel_url: str
    user_ids: List[str]
    name: Optional[str] = None


class SendMessageRequest(BaseModel):
    channel_url: str
    message: str


@router.post("/users")
async def create_sendbird_user(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create or update Sendbird user"""
    try:
        nickname = f"{current_user.first_name} {current_user.last_name}".strip() or current_user.email
        user_data = SendbirdClient.create_user(
            user_id=str(current_user.id),
            nickname=nickname,
            profile_url=None
        )
        
        if user_data:
            logger.info(f"Sendbird user created/updated: {current_user.id}")
            return {"message": "User created successfully", "user_id": str(current_user.id)}
        else:
            raise BadRequestException("Failed to create Sendbird user")
    except Exception as e:
        logger.error(f"Failed to create Sendbird user: {e}")
        raise BadRequestException("Failed to create Sendbird user")


@router.post("/channels")
async def create_channel(
    channel_data: CreateChannelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a Sendbird channel"""
    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)
    
    # Check subscription feature
    if not has_feature(plan, Feature.CHAT):
        raise ForbiddenException("Chat feature requires Annual subscription")
    
    # Ensure current user is in the channel
    if str(current_user.id) not in channel_data.user_ids:
        channel_data.user_ids.append(str(current_user.id))
    
    try:
        channel = SendbirdClient.create_channel(
            channel_url=channel_data.channel_url,
            user_ids=channel_data.user_ids,
            name=channel_data.name
        )
        
        if channel:
            logger.info(f"Channel created: {channel_data.channel_url}")
            return {"message": "Channel created successfully", "channel": channel}
        else:
            raise BadRequestException("Failed to create channel")
    except Exception as e:
        logger.error(f"Failed to create channel: {e}")
        raise BadRequestException("Failed to create channel")


@router.post("/messages")
async def send_message(
    message_data: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Send a message in a channel"""
    try:
        message = SendbirdClient.send_message(
            channel_url=message_data.channel_url,
            user_id=str(current_user.id),
            message=message_data.message
        )
        
        if message:
            logger.info(f"Message sent to channel: {message_data.channel_url}")
            return {"message": "Message sent successfully", "message_id": message.get("message_id")}
        else:
            raise BadRequestException("Failed to send message")
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        raise BadRequestException("Failed to send message")


@router.get("/channels")
async def get_channels(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get channels for current user"""
    try:
        channels = SendbirdClient.get_channels(str(current_user.id), limit=limit)
        if channels:
            return {"channels": channels.get("channels", [])}
        else:
            return {"channels": []}
    except Exception as e:
        logger.error(f"Failed to get channels: {e}")
        raise BadRequestException("Failed to get channels")


@router.get("/channels/{channel_url}")
async def get_channel(
    channel_url: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get channel details"""
    try:
        channel = SendbirdClient.get_channel(channel_url)
        if channel:
            # Verify user is in channel
            members = channel.get("members", [])
            user_in_channel = any(str(member.get("user_id")) == str(current_user.id) for member in members)
            if not user_in_channel:
                raise HTTPException(status_code=403, detail="Access denied")
            return channel
        else:
            raise NotFoundException("Channel", channel_url)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get channel: {e}")
        raise BadRequestException("Failed to get channel")


@router.get("/channels/{channel_url}/messages")
async def get_messages(
    channel_url: str,
    limit: int = Query(50, ge=1, le=100),
    token: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get messages from a channel"""
    try:
        # Verify user has access
        channel = SendbirdClient.get_channel(channel_url)
        if not channel:
            raise NotFoundException("Channel", channel_url)
        
        members = channel.get("members", [])
        user_in_channel = any(str(member.get("user_id")) == str(current_user.id) for member in members)
        if not user_in_channel:
            raise HTTPException(status_code=403, detail="Access denied")
        
        messages = SendbirdClient.get_messages(channel_url, limit=limit, token=token)
        if messages:
            return messages
        else:
            return {"messages": [], "next": None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get messages: {e}")
        raise BadRequestException("Failed to get messages")


@router.put("/channels/{channel_url}")
async def update_channel(
    channel_url: str,
    name: Optional[str] = Body(None),
    cover_url: Optional[str] = Body(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update channel details"""
    try:
        # Verify user has access
        channel = SendbirdClient.get_channel(channel_url)
        if not channel:
            raise NotFoundException("Channel", channel_url)
        
        members = channel.get("members", [])
        user_in_channel = any(str(member.get("user_id")) == str(current_user.id) for member in members)
        if not user_in_channel:
            raise HTTPException(status_code=403, detail="Access denied")
        
        updated = SendbirdClient.update_channel(channel_url, name=name, cover_url=cover_url)
        if updated:
            return {"message": "Channel updated successfully", "channel": updated}
        else:
            raise BadRequestException("Failed to update channel")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update channel: {e}")
        raise BadRequestException("Failed to update channel")


@router.delete("/channels/{channel_url}")
async def delete_channel(
    channel_url: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a channel"""
    try:
        # Verify user has access
        channel = SendbirdClient.get_channel(channel_url)
        if not channel:
            raise NotFoundException("Channel", channel_url)
        
        members = channel.get("members", [])
        user_in_channel = any(str(member.get("user_id")) == str(current_user.id) for member in members)
        if not user_in_channel:
            raise HTTPException(status_code=403, detail="Access denied")
        
        deleted = SendbirdClient.delete_channel(channel_url)
        if deleted:
            return {"message": "Channel deleted successfully"}
        else:
            raise BadRequestException("Failed to delete channel")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete channel: {e}")
        raise BadRequestException("Failed to delete channel")

