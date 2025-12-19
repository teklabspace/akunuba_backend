from sqlalchemy import Column, Numeric, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, unique=True)
    total_value = Column(Numeric(20, 2), default=0, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    performance_data = Column(JSONB)
    asset_allocation = Column(JSONB)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account", back_populates="portfolio")

