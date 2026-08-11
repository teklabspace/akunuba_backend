from sqlalchemy import Column, String, Numeric, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid


class Transfer(Base):
    """Money transfers initiated from the cash-flow screen.

    Replaces the old stub endpoint that confirmed transfers without recording
    anything. ``from_linked_account_id`` references the Plaid-linked source
    account for internal transfers; external transfers carry a wallet address
    instead. Statuses: pending -> completed/failed/cancelled (no processor is
    wired yet, so rows stay pending until a real rail exists).
    """
    __tablename__ = "transfers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    transfer_type = Column(String(20), nullable=False)  # internal | external
    from_linked_account_id = Column(UUID(as_uuid=True), ForeignKey("linked_accounts.id"), nullable=True)
    to_linked_account_id = Column(UUID(as_uuid=True), ForeignKey("linked_accounts.id"), nullable=True)
    wallet_address = Column(String(255))
    amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    transfer_date = Column(Date, nullable=False)
    frequency = Column(String(20), nullable=False, default="one-time")
    description = Column(String(500))
    status = Column(String(20), nullable=False, default="pending")
    confirmation_number = Column(String(40), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account")
