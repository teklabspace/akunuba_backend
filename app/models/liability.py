from sqlalchemy import Column, String, Numeric, Date, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid


class Liability(Base):
    """Detailed liability data for one credit/mortgage/student-loan linked
    account (Plaid's Liabilities product). One row per account — Plaid
    returns exactly one liability object per account, not a history.

    Common, queryable fields (payment/due-date/statement/overdue) are real
    columns; the long tail of type-specific fields Plaid returns (credit's
    per-APR-bucket array, mortgage's loan terms/origination, student's
    servicer/repayment plan) live in `details` rather than three separate
    tables, mirroring the metadata-JSONB pattern already used on
    LinkedAccount/Transaction.
    """
    __tablename__ = "liabilities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    linked_account_id = Column(UUID(as_uuid=True), ForeignKey("linked_accounts.id"), nullable=False, unique=True)
    # "credit" | "mortgage" | "student" — which of Plaid's three liability
    # buckets this account's data came from.
    liability_type = Column(String(20), nullable=False)
    last_payment_amount = Column(Numeric(20, 2))
    last_payment_date = Column(Date)
    next_payment_due_date = Column(Date)
    minimum_payment_amount = Column(Numeric(20, 2))
    last_statement_balance = Column(Numeric(20, 2))
    is_overdue = Column(Boolean)
    details = Column(JSONB)
    last_synced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    linked_account = relationship("LinkedAccount", back_populates="liability")
