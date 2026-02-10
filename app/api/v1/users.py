from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.models.account import Account
from app.schemas.user import UserResponse, UserUpdate
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.permissions import Role, Permission, has_permission
from app.core.security import verify_password, get_password_hash
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel, EmailStr
import json
import secrets
import base64
import io

# Try to import pyotp for 2FA, fallback if not available
try:
    import pyotp
    import qrcode
    from qrcode.image.pil import PilImage
    TOTP_AVAILABLE = True
    logger.info("2FA libraries (pyotp, qrcode) loaded successfully")
except ImportError as e:
    TOTP_AVAILABLE = False
    pyotp = None
    qrcode = None
    logger.warning(f"2FA libraries not available: {e}. Install with: pip install pyotp qrcode[pil]")

router = APIRouter()


# ==================== SCHEMAS ====================

class NotificationPreferencesResponse(BaseModel):
    email_alerts: bool
    push_notifications: bool
    weekly_reports: bool
    market_updates: bool


class NotificationPreferencesUpdate(BaseModel):
    email_alerts: Optional[bool] = None
    push_notifications: Optional[bool] = None
    weekly_reports: Optional[bool] = None
    market_updates: Optional[bool] = None


class PrivacyPreferencesResponse(BaseModel):
    profile_visible: bool
    show_portfolio: bool
    two_factor_auth_enabled: bool
    two_factor_auth_verified: bool


class PrivacyPreferencesUpdate(BaseModel):
    profile_visible: Optional[bool] = None
    show_portfolio: Optional[bool] = None


class TwoFactorAuthStatusResponse(BaseModel):
    enabled: bool
    verified: bool
    method: Optional[str] = None


class TwoFactorAuthSetupResponse(BaseModel):
    secret: str
    qr_code_url: str
    backup_codes: List[str]


class TwoFactorAuthVerify(BaseModel):
    code: str


class TwoFactorAuthToggle(BaseModel):
    enabled: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class DeactivateAccountRequest(BaseModel):
    reason: Optional[str] = None
    password_confirmation: str


class DeleteAccountRequest(BaseModel):
    password_confirmation: str
    confirmation_text: str


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


# ==================== NOTIFICATION PREFERENCES ====================

@router.get("/notifications", response_model=NotificationPreferencesResponse)
async def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user notification preferences"""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    )
    preferences = result.scalar_one_or_none()
    
    # Create default preferences if they don't exist
    if not preferences:
        preferences = UserPreferences(
            user_id=current_user.id,
            email_alerts=True,
            push_notifications=False,
            weekly_reports=True,
            market_updates=True
        )
        db.add(preferences)
        await db.commit()
        await db.refresh(preferences)
    
    return NotificationPreferencesResponse(
        email_alerts=preferences.email_alerts,
        push_notifications=preferences.push_notifications,
        weekly_reports=preferences.weekly_reports,
        market_updates=preferences.market_updates
    )


@router.put("/notifications", response_model=NotificationPreferencesResponse)
async def update_notification_preferences(
    preferences_data: NotificationPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user notification preferences"""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        preferences = UserPreferences(user_id=current_user.id)
        db.add(preferences)
    
    if preferences_data.email_alerts is not None:
        preferences.email_alerts = preferences_data.email_alerts
    if preferences_data.push_notifications is not None:
        preferences.push_notifications = preferences_data.push_notifications
    if preferences_data.weekly_reports is not None:
        preferences.weekly_reports = preferences_data.weekly_reports
    if preferences_data.market_updates is not None:
        preferences.market_updates = preferences_data.market_updates
    
    await db.commit()
    await db.refresh(preferences)
    
    logger.info(f"Notification preferences updated for user: {current_user.id}")
    
    return NotificationPreferencesResponse(
        email_alerts=preferences.email_alerts,
        push_notifications=preferences.push_notifications,
        weekly_reports=preferences.weekly_reports,
        market_updates=preferences.market_updates
    )


# ==================== PRIVACY PREFERENCES ====================

@router.get("/privacy", response_model=PrivacyPreferencesResponse)
async def get_privacy_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user privacy preferences"""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    )
    preferences = result.scalar_one_or_none()
    
    # Create default preferences if they don't exist
    if not preferences:
        preferences = UserPreferences(
            user_id=current_user.id,
            profile_visible=True,
            show_portfolio=False
        )
        db.add(preferences)
        await db.commit()
        await db.refresh(preferences)
    
    return PrivacyPreferencesResponse(
        profile_visible=preferences.profile_visible,
        show_portfolio=preferences.show_portfolio,
        two_factor_auth_enabled=current_user.two_factor_auth_enabled,
        two_factor_auth_verified=current_user.two_factor_auth_verified
    )


@router.put("/privacy", response_model=PrivacyPreferencesResponse)
async def update_privacy_preferences(
    preferences_data: PrivacyPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user privacy preferences"""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == current_user.id)
    )
    preferences = result.scalar_one_or_none()
    
    if not preferences:
        preferences = UserPreferences(user_id=current_user.id)
        db.add(preferences)
    
    if preferences_data.profile_visible is not None:
        preferences.profile_visible = preferences_data.profile_visible
    if preferences_data.show_portfolio is not None:
        preferences.show_portfolio = preferences_data.show_portfolio
    
    await db.commit()
    await db.refresh(preferences)
    await db.refresh(current_user)
    
    logger.info(f"Privacy preferences updated for user: {current_user.id}")
    
    return PrivacyPreferencesResponse(
        profile_visible=preferences.profile_visible,
        show_portfolio=preferences.show_portfolio,
        two_factor_auth_enabled=current_user.two_factor_auth_enabled,
        two_factor_auth_verified=current_user.two_factor_auth_verified
    )


# ==================== TWO-FACTOR AUTHENTICATION ====================

@router.get("/two-factor-auth/status", response_model=TwoFactorAuthStatusResponse)
async def get_2fa_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get two-factor authentication status"""
    return TwoFactorAuthStatusResponse(
        enabled=current_user.two_factor_auth_enabled,
        verified=current_user.two_factor_auth_verified,
        method=current_user.two_factor_auth_method
    )


@router.post("/two-factor-auth/setup", response_model=TwoFactorAuthSetupResponse)
async def setup_2fa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Setup two-factor authentication and generate QR code"""
    if not TOTP_AVAILABLE:
        raise BadRequestException("2FA functionality is not available. Please install pyotp and qrcode libraries.")
    
    # Generate a secret
    secret = pyotp.random_base32()
    
    # Store secret (but don't mark as verified yet)
    current_user.two_factor_auth_secret = secret
    current_user.two_factor_auth_method = "totp"
    current_user.two_factor_auth_enabled = False  # Will be enabled after verification
    current_user.two_factor_auth_verified = False
    
    # Generate backup codes
    backup_codes = [secrets.token_hex(4) for _ in range(10)]
    current_user.two_factor_backup_codes = json.dumps(backup_codes)
    
    await db.commit()
    await db.refresh(current_user)
    
    # Generate TOTP URI (Google Authenticator compatible)
    # Format: otpauth://totp/Issuer:AccountName?secret=SECRET&issuer=Issuer
    totp = pyotp.TOTP(secret)
    totp_uri = totp.provisioning_uri(
        name=current_user.email,
        issuer_name="Fullego"
    )
    
    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(totp_uri)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to base64 data URL
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    img_str = base64.b64encode(buffer.getvalue()).decode()
    qr_code_url = f"data:image/png;base64,{img_str}"
    
    logger.info(f"2FA setup initiated for user: {current_user.id}")
    
    return TwoFactorAuthSetupResponse(
        secret=secret,
        qr_code_url=qr_code_url,
        backup_codes=backup_codes
    )


@router.post("/two-factor-auth/verify", response_model=Dict[str, Any])
async def verify_2fa(
    verify_data: TwoFactorAuthVerify,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Verify two-factor authentication setup"""
    if not TOTP_AVAILABLE:
        raise BadRequestException("2FA functionality is not available.")
    
    if not current_user.two_factor_auth_secret:
        raise BadRequestException("2FA setup not initiated. Please setup 2FA first.")
    
    # Verify the code
    totp = pyotp.TOTP(current_user.two_factor_auth_secret)
    
    # Check if code is valid
    is_valid = totp.verify(verify_data.code, valid_window=1)
    
    # Also check backup codes
    backup_codes_valid = False
    if current_user.two_factor_backup_codes:
        try:
            backup_codes = json.loads(current_user.two_factor_backup_codes)
            if verify_data.code in backup_codes:
                backup_codes_valid = True
                # Remove used backup code
                backup_codes.remove(verify_data.code)
                current_user.two_factor_backup_codes = json.dumps(backup_codes)
        except (json.JSONDecodeError, ValueError):
            pass
    
    if not is_valid and not backup_codes_valid:
        raise BadRequestException("Invalid verification code")
    
    # Mark as verified and enabled
    current_user.two_factor_auth_verified = True
    current_user.two_factor_auth_enabled = True
    
    await db.commit()
    await db.refresh(current_user)
    
    logger.info(f"2FA verified and enabled for user: {current_user.id}")
    
    return {
        "message": "2FA verified and enabled successfully",
        "verified": True,
        "enabled": True
    }


@router.put("/two-factor-auth", response_model=Dict[str, Any])
async def toggle_2fa(
    toggle_data: TwoFactorAuthToggle,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Enable or disable two-factor authentication"""
    if toggle_data.enabled:
        if not current_user.two_factor_auth_verified:
            raise BadRequestException("2FA must be verified before it can be enabled")
        current_user.two_factor_auth_enabled = True
        message = "2FA enabled successfully"
    else:
        current_user.two_factor_auth_enabled = False
        message = "2FA disabled successfully"
    
    await db.commit()
    await db.refresh(current_user)
    
    logger.info(f"2FA toggled to {toggle_data.enabled} for user: {current_user.id}")
    
    return {
        "message": message,
        "enabled": current_user.two_factor_auth_enabled
    }


# ==================== CHANGE PASSWORD ====================

@router.put("/change-password", response_model=Dict[str, Any])
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Change user password"""
    # Verify current password
    if not verify_password(password_data.current_password, current_user.hashed_password):
        raise BadRequestException("Current password is incorrect")
    
    # Validate new password
    if password_data.new_password != password_data.confirm_password:
        raise BadRequestException("New password and confirmation do not match")
    
    if len(password_data.new_password) < 8:
        raise BadRequestException("Password must be at least 8 characters long")
    
    # Check if new password is same as current
    if verify_password(password_data.new_password, current_user.hashed_password):
        raise BadRequestException("New password must be different from current password")
    
    # Update password
    current_user.hashed_password = get_password_hash(password_data.new_password)
    
    await db.commit()
    
    logger.info(f"Password changed for user: {current_user.id}")
    
    return {
        "message": "Password changed successfully"
    }


# ==================== DEACTIVATE ACCOUNT ====================

@router.post("/deactivate", response_model=Dict[str, Any])
async def deactivate_account(
    deactivate_data: DeactivateAccountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate user account (soft delete)"""
    # Verify password
    if not verify_password(deactivate_data.password_confirmation, current_user.hashed_password):
        raise BadRequestException("Password is incorrect")
    
    # Soft delete: deactivate account
    current_user.is_active = False
    current_user.deactivated_at = datetime.utcnow()
    
    await db.commit()
    
    logger.info(f"Account deactivated for user: {current_user.id}")
    
    return {
        "message": "Account deactivated successfully",
        "deactivated_at": current_user.deactivated_at.isoformat() if current_user.deactivated_at else None
    }


# ==================== DELETE ACCOUNT ====================

@router.post("/delete", response_model=Dict[str, Any])
async def delete_account(
    delete_data: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Permanently delete user account (hard delete)"""
    # Verify password
    if not verify_password(delete_data.password_confirmation, current_user.hashed_password):
        raise BadRequestException("Password is incorrect")
    
    # Verify confirmation text
    if delete_data.confirmation_text != "DELETE":
        raise BadRequestException("Confirmation text must be 'DELETE'")
    
    # Hard delete: remove user from database
    user_id = current_user.id
    await db.delete(current_user)
    await db.commit()
    
    logger.warning(f"Account permanently deleted for user: {user_id}")
    
    return {
        "message": "Account deleted successfully"
    }

