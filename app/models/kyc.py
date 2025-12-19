from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SQLEnum, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class KYCStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class KYCVerification(Base):
    __tablename__ = "kyc_verifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, unique=True)
    persona_inquiry_id = Column(String(255), unique=True)
    status = Column(SQLEnum(KYCStatus), default=KYCStatus.NOT_STARTED, nullable=False)
    verification_level = Column(String(50))
    persona_response = Column(JSONB)
    documents_submitted = Column(Boolean, default=False)
    verified_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")

