from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class CashEntryType(str, Enum):
    """Why cash moved. Kept explicit so the ledger stays auditable."""
    DEPOSIT = "deposit"          # linked bank -> trading cash
    WITHDRAWAL = "withdrawal"    # trading cash -> linked bank
    TRADE_BUY = "trade_buy"      # debit, settled order
    TRADE_SELL = "trade_sell"    # credit, settled order
    ADJUSTMENT = "adjustment"    # manual correction


class CashTransaction(Base):
    """Append-only audit trail behind ``accounts.cash_balance``.

    ``amount`` is SIGNED (negative debits, positive credits) so the balance is
    simply the running sum; ``balance_after`` snapshots the materialized
    balance at the time of the entry, which makes drift detectable.
    """
    __tablename__ = "cash_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True)
    # values_callable is required: without it SQLAlchemy sends the member NAME
    # ("DEPOSIT") while the PG type holds lowercase values -> InvalidTextRepresentation.
    entry_type = Column(
        SQLEnum(
            CashEntryType,
            name="cashentrytype",
            values_callable=lambda enum_class: [member.value for member in enum_class],
        ),
        nullable=False,
    )
    amount = Column(Numeric(20, 2), nullable=False)
    balance_after = Column(Numeric(20, 2), nullable=False)
    description = Column(String(255))
    # Provenance: which order or which bank account this entry came from.
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    linked_account_id = Column(UUID(as_uuid=True), ForeignKey("linked_accounts.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    account = relationship("Account")
    order = relationship("Order")
    linked_account = relationship("LinkedAccount")
