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


class LinkedAccount(Base):
    __tablename__ = "linked_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    plaid_item_id = Column(String(255))
    plaid_access_token = Column(String(500))
    account_type = Column(SQLEnum(AccountType), nullable=False)
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

