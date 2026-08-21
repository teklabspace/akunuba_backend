from sqlalchemy import Column, String, Numeric, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid


class Security(Base):
    """A security Plaid reports holdings against. Cached and shared across
    every account/holding that references it (multiple accounts commonly
    hold the same stock/fund)."""
    __tablename__ = "securities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plaid_security_id = Column(String(255), unique=True, nullable=False, index=True)
    ticker_symbol = Column(String(20))
    name = Column(String(255))
    # Plaid's security type: equity, etf, mutual fund, fixed income, cash,
    # derivative, crypto, loan, other.
    security_type = Column(String(50))
    close_price = Column(Numeric(20, 4))
    close_price_as_of = Column(Date)
    currency = Column(String(3), default="USD")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    holdings = relationship("InvestmentHolding", back_populates="security")


class InvestmentHolding(Base):
    """One (linked_account, security) position, replaced wholesale on each
    sync — Plaid's /investments/holdings/get is a full current snapshot, not
    a delta, so there is no history to preserve here."""
    __tablename__ = "investment_holdings"
    __table_args__ = (
        UniqueConstraint("linked_account_id", "security_id", name="uq_holding_account_security"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    linked_account_id = Column(UUID(as_uuid=True), ForeignKey("linked_accounts.id"), nullable=False, index=True)
    security_id = Column(UUID(as_uuid=True), ForeignKey("securities.id"), nullable=False)
    quantity = Column(Numeric(24, 8), nullable=False)
    cost_basis = Column(Numeric(20, 2))
    # institution_value is the holding's current market value as reported by
    # Plaid (quantity * institution_price, but Plaid gives it directly and
    # that's the figure that must feed any "what is this account worth" math
    # — never re-derive it from quantity * price locally).
    institution_value = Column(Numeric(20, 2), nullable=False)
    institution_price = Column(Numeric(20, 4))
    institution_price_as_of = Column(Date)
    currency = Column(String(3), default="USD")
    last_synced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    linked_account = relationship("LinkedAccount", back_populates="holdings")
    security = relationship("Security", back_populates="holdings")
