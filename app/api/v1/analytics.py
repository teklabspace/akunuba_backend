from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, Dict, Any, List
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.integrations.posthog_client import PosthogClient
from app.core.exceptions import NotFoundException
from app.utils.logger import logger
from pydantic import BaseModel

router = APIRouter()


class TrackEventRequest(BaseModel):
    event: str
    properties: Optional[Dict[str, Any]] = None


class IdentifyUserRequest(BaseModel):
    properties: Dict[str, Any]


@router.post("/identify")
async def identify_user(
    identify_data: IdentifyUserRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Identify user in PostHog analytics"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    properties = {
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "role": current_user.role.value,
        "is_verified": current_user.is_verified,
        **identify_data.properties
    }
    
    success = PosthogClient.identify(
        distinct_id=str(current_user.id),
        properties=properties
    )
    
    if success:
        logger.info(f"User identified in PostHog: {current_user.id}")
        return {"message": "User identified successfully"}
    else:
        return {"message": "PostHog not configured or identification failed"}


@router.post("/track")
async def track_event(
    event_data: TrackEventRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Track an event in PostHog analytics"""
    success = PosthogClient.track(
        distinct_id=str(current_user.id),
        event=event_data.event,
        properties=event_data.properties
    )
    
    if success:
        logger.info(f"Event tracked in PostHog: {event_data.event} for user {current_user.id}")
        return {"message": "Event tracked successfully"}
    else:
        return {"message": "PostHog not configured or tracking failed"}


@router.post("/track-batch")
async def track_events_batch(
    events: List[TrackEventRequest],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Track multiple events in a single request"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    results = []
    for event_data in events:
        success = PosthogClient.track(
            distinct_id=str(current_user.id),
            event=event_data.event,
            properties=event_data.properties
        )
        results.append({
            "event": event_data.event,
            "success": success
        })
    
    success_count = sum(1 for r in results if r["success"])
    logger.info(f"Batch tracked {success_count}/{len(events)} events for user {current_user.id}")
    
    return {
        "message": f"Tracked {success_count}/{len(events)} events",
        "results": results
    }


@router.post("/page-view")
async def track_page_view(
    page_name: str,
    page_url: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Track a page view event"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    event_properties = {
        "page_name": page_name,
        "page_url": page_url or "",
        **(properties or {})
    }
    
    success = PosthogClient.track(
        distinct_id=str(current_user.id),
        event="$pageview",
        properties=event_properties
    )
    
    if success:
        logger.info(f"Page view tracked: {page_name} for user {current_user.id}")
        return {"message": "Page view tracked successfully"}
    else:
        return {"message": "PostHog not configured or tracking failed"}


@router.get("/dashboard")
async def get_analytics_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get analytics dashboard data (placeholder - PostHog has its own dashboard)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Check if PostHog is configured
    posthog_configured = PosthogClient.get_client() is not None
    
    # Return dashboard info and links
    return {
        "user_id": str(current_user.id),
        "posthog_configured": posthog_configured,
        "dashboard_url": "https://app.posthog.com" if posthog_configured else None,
        "note": "Use PostHog dashboard for detailed analytics. This endpoint provides basic tracking status.",
        "tracking_enabled": posthog_configured,
        "features": {
            "event_tracking": posthog_configured,
            "user_identification": posthog_configured,
            "batch_tracking": posthog_configured,
            "page_view_tracking": posthog_configured
        }
    }

