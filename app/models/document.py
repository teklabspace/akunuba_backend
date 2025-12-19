from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class DocumentType(str, Enum):
    KYC = "kyc"
    KYC_DOCUMENT = "kyc_document"
    ASSET_DOCUMENT = "asset_document"
    CONTRACT = "contract"
    INVOICE = "invoice"
    REPORT = "report"
    OTHER = "other"


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    document_type = Column(SQLEnum(DocumentType), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    mime_type = Column(String(100))
    supabase_storage_path = Column(String(500))
    description = Column(Text)
    meta_data = Column("metadata", String(1000))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")

