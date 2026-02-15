from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from app.database import get_db
from app.models.user import User
from app.models.account import Account
from app.models.kyc import KYCVerification, KYCStatus
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token, decode_refresh_token, generate_otp, generate_verification_token, generate_reset_token
import json

# Try to import pyotp for 2FA verification during login
try:
    import pyotp
    TOTP_AVAILABLE = True
except ImportError:
    TOTP_AVAILABLE = False
    pyotp = None
from app.core.exceptions import UnauthorizedException, ConflictException, NotFoundException, BadRequestException
from app.schemas.user import UserCreate, UserLogin, TokenResponse, LoginUserResponse, OTPRequest, OTPVerify, PasswordResetRequest, PasswordReset, RefreshTokenRequest, EmailVerificationRequest
from app.utils.logger import logger
from datetime import timedelta, datetime, timezone
from app.config import settings
from app.integrations.supabase_client import SupabaseClient
from app.services.email_service import EmailService
import httpx
import secrets

router = APIRouter()
security = HTTPBearer()

class GoogleAuthRequest(BaseModel):
    code: str
    redirect_uri: str = None

class GoogleTokenRequest(BaseModel):
    id_token: str


async def get_user_verification_status(user: User, db: AsyncSession) -> dict:
    """Helper function to get user verification status (KYC and email)
    
    Business Rule: Email must be verified before KYC can be approved.
    So is_kyc_verified can only be True if is_email_verified is also True.
    """
    # Check if email is verified (via OTP or email verification link)
    # Email is verified if:
    # 1. email_verified_at is set (email verification link clicked), OR
    # 2. is_verified is True (OTP verified or email verified)
    is_email_verified = user.email_verified_at is not None or user.is_verified
    
    # Check if KYC is approved (only possible if email is verified first)
    is_kyc_verified = False
    if is_email_verified:  # Only check KYC if email is verified
        try:
            # Get user's account
            account_result = await db.execute(
                select(Account).where(Account.user_id == user.id)
            )
            account = account_result.scalar_one_or_none()
            
            if account:
                # Check if KYC exists and is approved
                kyc_result = await db.execute(
                    select(KYCVerification).where(KYCVerification.account_id == account.id)
                )
                kyc = kyc_result.scalar_one_or_none()
                if kyc and kyc.status == KYCStatus.APPROVED:
                    is_kyc_verified = True
        except Exception as e:
            logger.warning(f"Error checking KYC status for user {user.id}: {e}")
    
    # Overall verification: True if KYC is verified (which requires email verification)
    # OR if only email is verified
    is_verified = is_kyc_verified or is_email_verified
    
    return {
        "is_verified": is_verified,
        "is_kyc_verified": is_kyc_verified,
        "is_email_verified": is_email_verified
    }

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    existing_user = await db.execute(select(User).where(User.email == user_data.email))
    if existing_user.scalar_one_or_none():
        raise ConflictException("User with this email already exists")
    hashed_password = get_password_hash(user_data.password)
    verification_token = generate_verification_token()
    otp_code = generate_otp()
    user = User(email=user_data.email, hashed_password=hashed_password, first_name=user_data.first_name, last_name=user_data.last_name, phone=user_data.phone, email_verification_token=verification_token, otp_code=otp_code, otp_expires_at=datetime.utcnow() + timedelta(minutes=10))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    try:
        supabase = SupabaseClient.get_client()
        supabase.auth.admin.create_user({"email": user_data.email, "password": user_data.password, "email_confirm": False, "user_metadata": {"first_name": user_data.first_name, "last_name": user_data.last_name, "phone": user_data.phone}})
    except Exception as e:
        logger.warning(f"Failed to create Supabase Auth user: {e}")
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    user.refresh_token = refresh_token
    await db.commit()
    await db.refresh(user)
    user_name = f"{user_data.first_name or ''} {user_data.last_name or ''}".strip() or "User"
    await EmailService.send_verification_email(to_email=user.email, to_name=user_name, verification_token=verification_token)
    await EmailService.send_otp_email(to_email=user.email, to_name=user_name, otp_code=otp_code)
    logger.info(f"User registered: {user.email}")
    
    # Get verification status (KYC and email)
    verification_status = await get_user_verification_status(user, db)
    
    # Return simplified user object with verification flags
    user_response = LoginUserResponse(
        id=user.id,
        role=user.role,
        is_verified=verification_status["is_verified"],
        is_kyc_verified=verification_status["is_kyc_verified"],
        is_email_verified=verification_status["is_email_verified"]
    )
    
    response_data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": user_response
    }
    if settings.APP_ENV == "development":
        response_data["otp"] = otp_code
        response_data["verification_token"] = verification_token
    return response_data


@router.post("/login")
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    """
    Login endpoint with 2FA support.
    
    If 2FA is enabled:
    - First call (without totp_code): Returns requires_2fa=true and temp_token
    - Second call (with totp_code): Verifies 2FA and returns access_token
    """
    try:
        result = await db.execute(select(User).where(User.email == credentials.email))
        user = result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Database error during login for {credentials.email}: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed. Please try again later."
        )
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise UnauthorizedException("Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
    
    # Check if 2FA is enabled and verified
    if user.two_factor_auth_enabled and user.two_factor_auth_verified:
        # 2FA is required
        if not credentials.totp_code:
            # First step: Password verified, now require 2FA code
            # Create a temporary token for 2FA verification (short-lived, 5 minutes)
            temp_token = create_access_token(
                data={"sub": str(user.id), "type": "2fa_pending", "login": True},
                expires_delta=timedelta(minutes=5)
            )
            
            logger.info(f"User {user.email} requires 2FA verification")
            
            return TokenResponse(
                access_token=None,
                refresh_token=None,
                token_type="bearer",
                user=None,
                requires_2fa=True,
                temp_token=temp_token,
                message="Please enter your 2FA code from your authenticator app"
            )
        
        # Second step: Verify 2FA code
        if not TOTP_AVAILABLE:
            raise BadRequestException("2FA verification is not available. Please contact support.")
        
        if not user.two_factor_auth_secret:
            raise BadRequestException("2FA is enabled but secret is missing. Please reset 2FA.")
        
        # Verify TOTP code
        totp = pyotp.TOTP(user.two_factor_auth_secret)
        is_valid = totp.verify(credentials.totp_code, valid_window=1)
        
        # Also check backup codes
        backup_codes_valid = False
        if user.two_factor_backup_codes:
            try:
                backup_codes = json.loads(user.two_factor_backup_codes)
                if credentials.totp_code in backup_codes:
                    backup_codes_valid = True
                    # Remove used backup code
                    backup_codes.remove(credentials.totp_code)
                    user.two_factor_backup_codes = json.dumps(backup_codes)
                    await db.commit()
            except (json.JSONDecodeError, ValueError):
                pass
        
        if not is_valid and not backup_codes_valid:
            raise UnauthorizedException("Invalid 2FA code. Please try again.")
        
        # 2FA verified, proceed with login
        logger.info(f"2FA verified for user {user.email}")
    
    # Complete login (2FA verified or not required)
    user.last_login = datetime.utcnow()
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    user.refresh_token = refresh_token
    await db.commit()
    await db.refresh(user)
    logger.info(f"User logged in: {user.email}")
    
    # Get verification status (KYC and email)
    verification_status = await get_user_verification_status(user, db)
    
    # Return simplified user object with verification flags
    user_response = LoginUserResponse(
        id=user.id,
        role=user.role,
        is_verified=verification_status["is_verified"],
        is_kyc_verified=verification_status["is_kyc_verified"],
        is_email_verified=verification_status["is_email_verified"]
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=user_response
    )

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token_endpoint(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
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
    await db.refresh(user)
    
    # Get verification status (KYC and email)
    verification_status = await get_user_verification_status(user, db)
    
    # Return simplified user object with verification flags
    user_response = LoginUserResponse(
        id=user.id,
        role=user.role,
        is_verified=verification_status["is_verified"],
        is_kyc_verified=verification_status["is_kyc_verified"],
        is_email_verified=verification_status["is_email_verified"]
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        user=user_response
    )

@router.post("/request-otp")
async def request_otp(request: OTPRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", request.email)
    otp_code = generate_otp()
    user.otp_code = otp_code
    user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.commit()
    user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "User"
    await EmailService.send_otp_email(to_email=user.email, to_name=user_name, otp_code=otp_code)
    if settings.APP_ENV == "development":
        return {"message": "OTP sent to your email", "otp": otp_code}
    return {"message": "OTP sent to your email"}

@router.post("/verify-otp")
async def verify_otp(request: OTPVerify, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(User).where(User.email == request.email))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException("User", request.email)
        
        # Convert both to strings for comparison to handle type mismatches
        user_otp = str(user.otp_code) if user.otp_code else None
        request_otp = str(request.otp_code).strip()
        
        if not user_otp or user_otp != request_otp:
            raise BadRequestException("Invalid OTP code")
        
        # Use timezone-aware datetime for comparison
        now = datetime.now(timezone.utc)
        if user.otp_expires_at and user.otp_expires_at < now:
            raise BadRequestException("OTP code has expired")
        
        # If purpose is "password_reset", don't clear the OTP - it will be used again in reset-password
        # For email verification or other purposes, clear the OTP after verification
        if request.purpose != "password_reset":
            user.otp_code = None
            user.otp_expires_at = None
            user.is_verified = True
        # For password reset, keep the OTP so it can be used in reset-password endpoint
        
        await db.commit()
        logger.info(f"OTP verified successfully for user: {user.email}, purpose: {request.purpose or 'email_verification'}")
        return {"message": "OTP verified successfully"}
    except (NotFoundException, BadRequestException) as e:
        # Re-raise known exceptions
        raise
    except Exception as e:
        # Log the full error with traceback for debugging
        logger.error(f"Error verifying OTP for {request.email}: {e}", exc_info=True)
        # In development, return the actual error message for debugging
        error_detail = str(e) if settings.APP_DEBUG else "An error occurred while verifying OTP"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail
        )


@router.post("/request-password-reset")
async def request_password_reset(request: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        return {"message": "If the email exists, a password reset link has been sent"}
    
    # Generate both reset token and OTP for flexibility
    reset_token = generate_reset_token()
    otp_code = generate_otp()
    
    user.password_reset_token = reset_token
    user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    user.otp_code = otp_code
    user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    
    await db.commit()
    user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "User"
    
    # Send both token-based reset email and OTP email
    await EmailService.send_password_reset_email(to_email=user.email, to_name=user_name, reset_token=reset_token)
    await EmailService.send_otp_email(to_email=user.email, to_name=user_name, otp_code=otp_code)
    
    return {"message": "If the email exists, a password reset link has been sent"}

@router.post("/reset-password")
async def reset_password(request: PasswordReset, db: AsyncSession = Depends(get_db)):
    # Support both token-based and OTP-based password reset
    if request.token:
        # Token-based reset (original method)
        result = await db.execute(select(User).where(User.password_reset_token == request.token))
        user = result.scalar_one_or_none()
        if not user:
            raise BadRequestException("Invalid reset token")
        if user.password_reset_expires_at and user.password_reset_expires_at < datetime.now(timezone.utc):
            raise BadRequestException("Reset token has expired")
    elif request.email and request.otp_code:
        # OTP-based reset
        result = await db.execute(select(User).where(User.email == request.email))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException("User", request.email)
        
        # Verify OTP
        user_otp = str(user.otp_code) if user.otp_code else None
        request_otp = str(request.otp_code).strip()
        
        if not user_otp or user_otp != request_otp:
            raise BadRequestException("Invalid OTP code")
        
        # Check OTP expiration
        now = datetime.now(timezone.utc)
        if user.otp_expires_at and user.otp_expires_at < now:
            raise BadRequestException("OTP code has expired")
    else:
        raise BadRequestException("No reset token found. Please use the link from your email or request a new password reset.")
    
    # Reset password
    user.hashed_password = get_password_hash(request.new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    user.otp_code = None
    user.otp_expires_at = None
    await db.commit()
    logger.info(f"Password reset successfully for user: {user.email}")
    return {"message": "Password reset successfully"}

@router.post("/verify-email")
async def verify_email(request: EmailVerificationRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email_verification_token == request.token))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", request.token)
    if user.is_verified:
        raise BadRequestException("Email already verified")
    user.is_verified = True
    user.email_verification_token = None
    user.email_verified_at = datetime.utcnow()
    await db.commit()
    return {"message": "Email verified successfully"}

@router.post("/resend-verification")
async def resend_verification(request: OTPRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("User", request.email)
    if user.is_verified:
        raise BadRequestException("Email already verified")
    verification_token = generate_verification_token()
    user.email_verification_token = verification_token
    await db.commit()
    user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "User"
    await EmailService.send_verification_email(to_email=user.email, to_name=user_name, verification_token=verification_token)
    return {"message": "Verification email sent"}
   