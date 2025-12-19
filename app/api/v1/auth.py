from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import EmailStr
from app.database import get_db
from app.models.user import User
from app.core.security import (
    verify_password, get_password_hash, create_access_token, create_refresh_token,
    decode_refresh_token, generate_otp, generate_verification_token, generate_reset_token
)
from app.core.exceptions import UnauthorizedException, ConflictException, NotFoundException, BadRequestException
from app.schemas.user import (
    UserCreate, UserLogin, TokenResponse, OTPRequest, OTPVerify,
    PasswordResetRequest, PasswordReset, RefreshTokenRequest, EmailVerificationRequest
)
from app.utils.logger import logger
from datetime import timedelta, datetime
from app.config import settings
from app.integrations.supabase_client import SupabaseClient
from app.services.email_service import EmailService

router = APIRouter()
security = HTTPBearer()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    existing_user = await db.execute(select(User).where(User.email == user_data.email))
    if existing_user.scalar_one_or_none():
        raise ConflictException("User with this email already exists")
    
    hashed_password = get_password_hash(user_data.password)
    verification_token = generate_verification_token()
    
    user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        phone=user_data.phone,
        email_verification_token=verification_token,
    )
    
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    # Create user in Supabase Auth
    try:
        supabase = SupabaseClient.get_client()
        supabase.auth.admin.create_user({
            "email": user_data.email,
            "password": user_data.password,
            "email_confirm": False,
            "user_metadata": {
                "first_name": user_data.first_name,
                "last_name": user_data.last_name,
                "phone": user_data.phone,
            }
        })
    except Exception as e:
        logger.warning(f"Failed to create Supabase Auth user: {e}")
    
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    user.refresh_token = refresh_token
    await db.commit()
    
    # Send verification email
    user_name = f"{user_data.first_name or ''} {user_data.last_name or ''}".strip() or "User"
    await EmailService.send_verification_email(
        to_email=user.email,
        to_name=user_name,
        verification_token=verification_token
    )
    
    logger.info(f"User registered: {user.email}")
    
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, token_type="bearer")


@router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise UnauthorizedException("Incorrect email or password")
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    user.last_login = datetime.utcnow()
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    user.refresh_token = refresh_token
    await db.commit()
    
    logger.info(f"User logged in: {user.email}")
    
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, token_type="bearer")


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_refresh_token(request.refresh_token)
    if not payload:
        raise UnauthorizedException("Invalid refresh token")
    
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user or user.refresh_token != request.refresh_token:
        raise UnauthorizedException("Invalid refresh token")
    
    access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})
    user.refresh_token = new_refresh_token
    await db.commit()
    
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token, token_type="bearer")


@router.post("/request-otp")
async def request_otp(request: OTPRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    
    if not user:
        raise NotFoundException("User not found")
    
    otp_code = generate_otp()
    user.otp_code = otp_code
    user.otp_expires_at = datetime.utcnow() + timedelta(minutes=10)
    await db.commit()
    
    # In production, send OTP via email/SMS
    logger.info(f"OTP generated for {user.email}: {otp_code}")
    
    return {"message": "OTP sent to your email/phone", "otp": otp_code}  # Remove otp in production


@router.post("/verify-otp")
async def verify_otp(request: OTPVerify, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    
    if not user:
        raise NotFoundException("User not found")
    
    if not user.otp_code or user.otp_code != request.otp_code:
        raise BadRequestException("Invalid OTP code")
    
    if user.otp_expires_at and user.otp_expires_at < datetime.utcnow():
        raise BadRequestException("OTP code has expired")
    
    user.otp_code = None
    user.otp_expires_at = None
    user.is_verified = True
    await db.commit()
    
    return {"message": "OTP verified successfully"}


@router.post("/request-password-reset")
async def request_password_reset(request: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    
    if not user:
        # Don't reveal if user exists
        return {"message": "If the email exists, a password reset link has been sent"}
    
    reset_token = generate_reset_token()
    user.password_reset_token = reset_token
    user.password_reset_expires_at = datetime.utcnow() + timedelta(hours=1)
    await db.commit()
    
    # Send password reset email
    user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "User"
    await EmailService.send_password_reset_email(
        to_email=user.email,
        to_name=user_name,
        reset_token=reset_token
    )
    
    logger.info(f"Password reset email sent to {user.email}")
    
    return {"message": "If the email exists, a password reset link has been sent"}


@router.post("/reset-password")
async def reset_password(request: PasswordReset, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.password_reset_token == request.token))
    user = result.scalar_one_or_none()
    
    if not user:
        raise BadRequestException("Invalid reset token")
    
    if user.password_reset_expires_at and user.password_reset_expires_at < datetime.utcnow():
        raise BadRequestException("Reset token has expired")
    
    user.hashed_password = get_password_hash(request.new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    await db.commit()
    
    return {"message": "Password reset successfully"}


@router.post("/verify-email")
async def verify_email(request: EmailVerificationRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email_verification_token == request.token))
    user = result.scalar_one_or_none()
    
    if not user:
        raise BadRequestException("Invalid verification token")
    
    user.is_verified = True
    user.email_verified_at = datetime.utcnow()
    user.email_verification_token = None
    await db.commit()
    
    return {"message": "Email verified successfully"}


@router.post("/resend-verification")
async def resend_verification(request: OTPRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    
    if not user:
        raise NotFoundException("User not found")
    
    if user.is_verified:
        raise BadRequestException("Email already verified")
    
    verification_token = generate_verification_token()
    user.email_verification_token = verification_token
    await db.commit()
    
    # Send verification email
    user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "User"
    await EmailService.send_verification_email(
        to_email=user.email,
        to_name=user_name,
        verification_token=verification_token
    )
    
    logger.info(f"Verification email sent to {user.email}")
    
    return {"message": "Verification email sent"}

