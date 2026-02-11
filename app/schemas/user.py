from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.core.permissions import Role


class UserBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = None  # 2FA code (required if 2FA is enabled)


class UserResponse(UserBase):
    id: UUID
    role: Role
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True


class LoginUserResponse(BaseModel):
    """Simplified user response for login/register/refresh endpoints"""
    id: UUID
    role: Role
    is_verified: bool  # Overall verification status (True if either KYC or email verified)
    is_kyc_verified: bool  # True if Persona KYC is approved
    is_email_verified: bool  # True if email is verified via OTP/email link

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: Optional[str] = None  # None if 2FA required
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[LoginUserResponse] = None
    requires_2fa: Optional[bool] = False  # True if 2FA code is required
    temp_token: Optional[str] = None  # Temporary token for 2FA verification
    message: Optional[str] = None  # Message for 2FA requirement


class OTPRequest(BaseModel):
    email: EmailStr


class OTPVerify(BaseModel):
    email: EmailStr
    otp_code: str
    purpose: Optional[str] = None  # "email_verification" or "password_reset"


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordReset(BaseModel):
    token: Optional[str] = None
    email: Optional[EmailStr] = None
    otp_code: Optional[str] = None
    new_password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class EmailVerificationRequest(BaseModel):
    token: str


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None

