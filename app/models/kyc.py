from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SQLEnum, Boolean, Integer
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


class KYCCaptureStatus(str, Enum):
    """Tracks whether we've pulled the user's Persona docs/images into our system."""
    NOT_CAPTURED = "not_captured"
    PENDING = "pending"
    CAPTURED = "captured"
    FAILED = "failed"


class KYCVerification(Base):
    __tablename__ = "kyc_verifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, unique=True)
    persona_inquiry_id = Column(String(255), unique=True)
    status = Column(SQLEnum(KYCStatus), default=KYCStatus.NOT_STARTED, nullable=False)
    verification_level = Column(String(50))
    persona_response = Column(JSONB)
    documents_submitted = Column(Boolean, default=False)
    # Structured data captured from Persona for admin review (see KYCDocument for files).
    extracted_fields = Column(JSONB)  # {name_first, name_last, birthdate, id_number, ...}
    checks = Column(JSONB)            # [{verification, name, status, reasons}]
    capture_status = Column(SQLEnum(KYCCaptureStatus), default=KYCCaptureStatus.NOT_CAPTURED, nullable=False)
    capture_error = Column(Text)
    captured_at = Column(DateTime(timezone=True))
    # Manual admin override audit (who last approved/rejected by hand).
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at = Column(DateTime(timezone=True))
    # Manual verification fallback: admin-sent tokenized link (the token is the
    # credential for the public selfie+ID submission endpoints). Cleared on use.
    manual_token = Column(String(255), unique=True, index=True)
    manual_token_expires_at = Column(DateTime(timezone=True))
    manual_submitted_at = Column(DateTime(timezone=True))
    verified_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    rejection_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    documents = relationship("KYCDocument", back_populates="kyc", cascade="all, delete-orphan")


class KYCDocument(Base):
    """A single file (ID front/back, selfie) captured from a user's Persona inquiry
    and stored in our private Supabase bucket for later admin review."""
    __tablename__ = "kyc_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kyc_id = Column(UUID(as_uuid=True), ForeignKey("kyc_verifications.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True)
    persona_inquiry_id = Column(String(255), index=True)
    # e.g. government_id_front | government_id_back | selfie_center
    document_type = Column(String(64), nullable=False)
    bucket = Column(String(128), nullable=False)
    file_path = Column(String(512), nullable=False)
    mime_type = Column(String(128))
    file_size = Column(Integer)
    persona_source_url = Column(Text)  # original Persona URL, kept for audit only
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    kyc = relationship("KYCVerification", back_populates="documents")

