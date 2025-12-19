from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.schemas.user import UserResponse, UserUpdate
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Role, Permission, has_permission
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel, EmailStr

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update current user profile"""
    if user_data.email and user_data.email != current_user.email:
        # Check if email already exists
        existing_result = await db.execute(
            select(User).where(User.email == user_data.email, User.id != current_user.id)
        )
        if existing_result.scalar_one_or_none():
            raise BadRequestException("Email already in use")
        current_user.email = user_data.email
        current_user.email_verified_at = None  # Require re-verification
    
    if user_data.first_name is not None:
        current_user.first_name = user_data.first_name
    if user_data.last_name is not None:
        current_user.last_name = user_data.last_name
    if user_data.phone is not None:
        current_user.phone = user_data.phone
    
    await db.commit()
    await db.refresh(current_user)
    
    logger.info(f"User profile updated: {current_user.id}")
    return current_user


@router.get("", response_model=List[UserResponse])
async def list_users(
    role: Optional[Role] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List users (admin only)"""
    if not has_permission(current_user.role, Permission.READ_USERS):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    query = select(User)
    
    if role:
        query = query.where(User.role == role)
    
    if search:
        query = query.where(
            func.lower(User.email).contains(search.lower()) |
            func.lower(User.first_name).contains(search.lower()) |
            func.lower(User.last_name).contains(search.lower())
        )
    
    # Pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    result = await db.execute(query.order_by(User.created_at.desc()))
    users = result.scalars().all()
    
    return users


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user by ID (admin only)"""
    if not has_permission(current_user.role, Permission.READ_USERS):
        # Users can only view their own profile
        if user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise NotFoundException("User", str(user_id))
    
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete user (admin only)"""
    if not has_permission(current_user.role, Permission.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    if user_id == current_user.id:
        raise BadRequestException("Cannot delete your own account")
    
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise NotFoundException("User", str(user_id))
    
    # Soft delete: deactivate user
    user.is_active = False
    await db.commit()
    
    logger.info(f"User deleted (soft): {user_id} by {current_user.id}")
    return None


@router.put("/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: UUID,
    new_role: Role = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user role (admin only)"""
    if not has_permission(current_user.role, Permission.MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise NotFoundException("User", str(user_id))
    
    user.role = new_role
    await db.commit()
    await db.refresh(user)
    
    logger.info(f"User role updated: {user_id} to {new_role.value} by {current_user.id}")
    return user


@router.get("/stats/summary")
async def get_user_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user statistics (admin only)"""
    if not has_permission(current_user.role, Permission.READ_USERS):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Total users
    total_result = await db.execute(select(func.count(User.id)))
    total_users = total_result.scalar() or 0
    
    # Active users
    active_result = await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )
    active_users = active_result.scalar() or 0
    
    # Verified users
    verified_result = await db.execute(
        select(func.count(User.id)).where(User.is_verified == True)
    )
    verified_users = verified_result.scalar() or 0
    
    # By role
    role_result = await db.execute(
        select(
            User.role,
            func.count(User.id).label("count")
        ).group_by(User.role)
    )
    by_role = {
        row.role.value: row.count
        for row in role_result.all()
    }
    
    return {
        "total_users": total_users,
        "active_users": active_users,
        "verified_users": verified_users,
        "by_role": by_role
    }

