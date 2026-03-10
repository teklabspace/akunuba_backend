from sqlalchemy import Column, String, DateTime, ForeignKey, Numeric, Integer, Boolean, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class ReferralStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Referral(Base):
    __tablename__ = "referrals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referrer_account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    referred_account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True)
    referral_code = Column(String(50), unique=True, nullable=False, index=True)
    referred_email = Column(String(255), nullable=True)
    status = Column(SQLEnum(ReferralStatus), default=ReferralStatus.PENDING, nullable=False)
    reward_amount = Column(Numeric(20, 2), default=0.00, nullable=False)
    reward_currency = Column(String(3), default="USD", nullable=False)
    reward_paid = Column(Boolean, default=False, nullable=False)
    reward_paid_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    referrer_account = relationship("Account", foreign_keys=[referrer_account_id], backref="referrals_made")
    referred_account = relationship("Account", foreign_keys=[referred_account_id], backref="referrals_received")


class ReferralReward(Base):
    __tablename__ = "referral_rewards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referral_id = Column(UUID(as_uuid=True), ForeignKey("referrals.id"), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    reward_type = Column(String(50), nullable=False)  # "signup", "first_payment", "subscription"
    paid = Column(Boolean, default=False, nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    referral = relationship("Referral", backref="rewards")
    account = relationship("Account", backref="referral_rewards")
