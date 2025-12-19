from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SQLEnum, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class KYBStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class KYBVerification(Base):
    __tablename__ = "kyb_verifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, unique=True)
    verification_type = Column(String(50), nullable=False)  # 'corporate' or 'trust'
    business_registration_number = Column(String(100))
    business_name = Column(String(255))
    business_address = Column(Text)
    ownership_structure = Column(JSONB)
    beneficial_owners = Column(JSONB)
    persona_kyb_inquiry_id = Column(String(255))
    status = Column(SQLEnum(KYBStatus), default=KYBStatus.NOT_STARTED, nullable=False)
    documents_submitted = Column(Boolean, default=False, nullable=False)
    verified_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account", back_populates="kyb_verification")

