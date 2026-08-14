"""Platform activity / audit log.

Deliberately generic: any actor doing anything to (or on behalf of) a subject
user lands here. `subject_user_id` is the person the action is ABOUT -- for
advisor access that is the client, which is what makes "who looked at my data"
an answerable question.

Append-only by convention: there is no update or delete path in the service.
"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    # The user the action concerns (the client, for advisor access).
    subject_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(64), nullable=False)
    entity_type = Column(String(40), nullable=True)
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    summary = Column(Text, nullable=True)
    # Column is "metadata" in SQL; `meta_data` attribute avoids clashing with
    # SQLAlchemy's Base.metadata (same trick as EntityAuditTrail).
    meta_data = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
