from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum as SQLEnum, Integer, Sequence
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class TicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Short, human-readable, sequential ticket number (displayed as "TCK-1042").
    # DB-backed sequence so it's monotonic and collision-free under concurrency.
    ticket_number = Column(
        Integer,
        Sequence("support_ticket_number_seq"),
        server_default=Sequence("support_ticket_number_seq").next_value(),
        unique=True,
        index=True,
    )
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(SQLEnum(TicketStatus), default=TicketStatus.OPEN, nullable=False)
    priority = Column(SQLEnum(TicketPriority), default=TicketPriority.MEDIUM, nullable=False)
    category = Column(String(50))  # Account/Login, KYC/KYB, Marketplace, etc.
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    sla_target_hours = Column(Integer)  # Target resolution time in hours
    first_response_at = Column(DateTime(timezone=True))
    sla_breached_at = Column(DateTime(timezone=True))
    escalation_count = Column(Integer, default=0)
    last_escalated_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    # CSAT: requester's satisfaction rating (1-5) after resolution, + optional note.
    satisfaction_rating = Column(Integer)
    satisfaction_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    assigned_user = relationship("User")
    replies = relationship("TicketReply", back_populates="ticket", cascade="all, delete-orphan")

