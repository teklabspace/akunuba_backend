from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid


class InvestmentStrategy(Base):
    """Community/platform investment strategies.

    ``account_id`` NULL means a platform-seeded strategy visible to everyone;
    non-NULL rows belong to the account (created via clone or authoring).
    ``cloned_from`` links a user's saved copy back to the original, which is
    how the detail endpoint answers ``is_saved``.
    """
    __tablename__ = "investment_strategies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True)
    cloned_from = Column(UUID(as_uuid=True), ForeignKey("investment_strategies.id"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(String(1000))
    full_description = Column(Text)
    author = Column(String(255))
    chart_type = Column(String(50))
    parameters = Column(JSONB)
    is_open_source = Column(Boolean, nullable=False, default=False)
    comment_count = Column(Integer, nullable=False, default=0)
    boost_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
