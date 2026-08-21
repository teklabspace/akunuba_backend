from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Enum as SQLEnum, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class AccountType(str, Enum):
    BANKING = "banking"
    BROKERAGE = "brokerage"
    CRYPTO = "crypto"
    # Credit/loan accounts (Plaid type "credit"/"loan"): deliberately NOT
    # BANKING — app/services/escrow_payout.py filters BANKING-only for payout
    # eligibility, and a credit card or mortgage must never qualify.
    OTHER = "other"


class LinkedAccount(Base):
    __tablename__ = "linked_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    plaid_item_id = Column(String(255))
    # Plaid's per-account id (distinct from plaid_item_id, which is shared by
    # every account under one Item/login). Required to correctly identify a
    # specific account when an Item returns more than one — see
    # app/services/plaid_categorization.py and banking_sync_service matching.
    plaid_account_id = Column(String(255))
    plaid_access_token = Column(String(500))
    # The PG enum is named linkedaccounttype — "accounttype" belongs to the
    # accounts table (INDIVIDUAL/CORPORATE/TRUST) and is a different type.
    account_type = Column(SQLEnum(AccountType, name="linkedaccounttype"), nullable=False)
    # Plaid's raw account type/subtype (e.g. "depository"/"checking",
    # "credit"/"credit card", "investment"/"401k"). Stored as plain strings,
    # not a constrained enum, since Plaid's subtype list is long and grows —
    # see app/services/plaid_categorization.py for the type->category mapping
    # every "is this cash?" filter (portfolio/investment/accounts/reports) uses.
    plaid_type = Column(String(50))
    plaid_subtype = Column(String(100))
    institution_name = Column(String(255))
    account_name = Column(String(255))
    account_number = Column(String(100))
    routing_number = Column(String(50))
    balance = Column(Numeric(20, 2))
    currency = Column(String(3), default="USD")
    is_active = Column(Boolean, default=True, nullable=False)
    last_synced_at = Column(DateTime(timezone=True))
    meta_data = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    transactions = relationship("Transaction", back_populates="linked_account")
    holdings = relationship("InvestmentHolding", back_populates="linked_account", cascade="all, delete-orphan")
    liability = relationship("Liability", back_populates="linked_account", uselist=False, cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    linked_account_id = Column(UUID(as_uuid=True), ForeignKey("linked_accounts.id"), nullable=False)
    plaid_transaction_id = Column(String(255), unique=True)
    amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    description = Column(String(500))
    category = Column(String(100))
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    meta_data = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    linked_account = relationship("LinkedAccount", back_populates="transactions")

