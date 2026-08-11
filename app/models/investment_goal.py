from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class GoalStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InvestmentGoal(Base):
    __tablename__ = "investment_goals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    name = Column(String(255), nullable=False)
    symbol = Column(String(50))
    target_amount = Column(Numeric(20, 2), nullable=False)
    target_quantity = Column(Numeric(20, 8))
    current_value = Column(Numeric(20, 2), nullable=False, default=0)
    current_quantity = Column(Numeric(20, 8), default=0)
    monthly_contribution = Column(Numeric(20, 2))
    risk_tolerance = Column(String(20))
    notes = Column(String(1000))
    status = Column(SQLEnum(GoalStatus), nullable=False, default=GoalStatus.ACTIVE)
    target_date = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
