from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class AssetType(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"
    ETF = "etf"
    BOND = "bond"
    OTHER = "other"


class InvestmentWatchlist(Base):
    __tablename__ = "investment_watchlist"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    symbol = Column(String(50), nullable=False)
    name = Column(String(255), nullable=True)
    asset_type = Column(SQLEnum(AssetType), nullable=False)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account")
