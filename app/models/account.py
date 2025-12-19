from sqlalchemy import Column, String, Boolean, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from enum import Enum
from app.database import Base
import uuid


class AccountType(str, Enum):
    INDIVIDUAL = "individual"
    CORPORATE = "corporate"
    TRUST = "trust"


class Account(Base):
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)
    account_type = Column(SQLEnum(AccountType), nullable=False)
    account_name = Column(String(255), nullable=False)
    is_joint = Column(Boolean, default=False, nullable=False)
    joint_users = Column(String(500))
    tax_id = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="account")
    assets = relationship("Asset", back_populates="account")
    portfolio = relationship("Portfolio", back_populates="account", uselist=False)
    kyb_verification = relationship("KYBVerification", back_populates="account", uselist=False)

