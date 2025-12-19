from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Enum as SQLEnum, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentMethod(str, Enum):
    CARD = "card"
    ACH = "ach"
    CRYPTO = "crypto"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PAST_DUE = "past_due"


class SubscriptionPlan(str, Enum):
    FREE = "free"
    MONTHLY = "monthly"
    ANNUAL = "annual"


class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    payment_method = Column(SQLEnum(PaymentMethod), nullable=False)
    status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)
    stripe_payment_intent_id = Column(String(255))
    stripe_charge_id = Column(String(255))
    description = Column(String(500))
    meta_data = Column("metadata", String(1000))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payments.id"))
    invoice_number = Column(String(100), unique=True, nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    description = Column(String(500))
    due_date = Column(DateTime(timezone=True))
    paid_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account")
    payment = relationship("Payment")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, unique=True)
    plan = Column(SQLEnum(SubscriptionPlan), nullable=False)
    status = Column(SQLEnum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE, nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    stripe_subscription_id = Column(String(255))
    current_period_start = Column(DateTime(timezone=True))
    current_period_end = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")


class Refund(Base):
    __tablename__ = "refunds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    stripe_refund_id = Column(String(255), unique=True)
    reason = Column(String(100))
    status = Column(String(50), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    payment = relationship("Payment")

