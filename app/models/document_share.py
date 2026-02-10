from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SQLEnum, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class SharePermission(str, Enum):
    VIEW = "view"
    DOWNLOAD = "download"
    EDIT = "edit"


class DocumentShare(Base):
    __tablename__ = "document_shares"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    shared_with_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    permission = Column(SQLEnum(SharePermission), default=SharePermission.VIEW, nullable=False)
    share_link = Column(String(500))  # For public sharing
    share_token = Column(String(100), unique=True)  # Token for share link
    expiry_date = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    document = relationship("Document")
    shared_with_user = relationship("User")
