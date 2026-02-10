from sqlalchemy import Column, String, Boolean, DateTime, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
from app.core.permissions import Role
import uuid


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    first_name = Column(String(100))
    last_name = Column(String(100))
    phone = Column(String(20))
    role = Column(SQLEnum(Role), default=Role.INVESTOR, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    email_verification_token = Column(String(255), nullable=True)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    otp_code = Column(String(6), nullable=True)
    otp_expires_at = Column(DateTime(timezone=True), nullable=True)
    password_reset_token = Column(String(255), nullable=True)
    password_reset_expires_at = Column(DateTime(timezone=True), nullable=True)
    refresh_token = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login = Column(DateTime(timezone=True))
    
    # Two-Factor Authentication
    two_factor_auth_enabled = Column(Boolean, default=False, nullable=False)
    two_factor_auth_verified = Column(Boolean, default=False, nullable=False)
    two_factor_auth_secret = Column(String(255), nullable=True)  # TOTP secret
    two_factor_auth_method = Column(String(20), nullable=True)  # 'totp', 'sms', 'email'
    two_factor_backup_codes = Column(String(1000), nullable=True)  # JSON array of backup codes
    deactivated_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete timestamp
    
    account = relationship("Account", back_populates="user", uselist=False)
    preferences = relationship("UserPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan")

