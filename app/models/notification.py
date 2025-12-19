from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SQLEnum, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class NotificationType(str, Enum):
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    OFFER_RECEIVED = "offer_received"
    OFFER_ACCEPTED = "offer_accepted"
    LISTING_APPROVED = "listing_approved"
    PAYMENT_RECEIVED = "payment_received"
    KYC_APPROVED = "kyc_approved"
    SUPPORT_REPLY = "support_reply"
    GENERAL = "general"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    notification_type = Column(SQLEnum(NotificationType), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(DateTime(timezone=True))
    meta_data = Column("metadata", String(1000))
    email_sent = Column(Boolean, default=False, nullable=False)
    email_sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account")

