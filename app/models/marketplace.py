from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Text, Enum as SQLEnum, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class ListingStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    SOLD = "sold"
    CANCELLED = "cancelled"


class OfferStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COUNTERED = "countered"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class EscrowStatus(str, Enum):
    PENDING = "pending"
    FUNDED = "funded"
    RELEASED = "released"
    REFUNDED = "refunded"
    DISPUTED = "disputed"


class MarketplaceListing(Base):
    __tablename__ = "marketplace_listings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    asking_price = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    listing_fee = Column(Numeric(20, 2))
    listing_fee_paid = Column(Boolean, default=False)
    status = Column(SQLEnum(ListingStatus), default=ListingStatus.DRAFT, nullable=False)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    approved_at = Column(DateTime(timezone=True))
    meta_data = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account")
    asset = relationship("Asset")
    offers = relationship("Offer", back_populates="listing")


class Offer(Base):
    __tablename__ = "offers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_listings.id"), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    offer_amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    status = Column(SQLEnum(OfferStatus), default=OfferStatus.PENDING, nullable=False)
    message = Column(Text)
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    listing = relationship("MarketplaceListing", back_populates="offers")
    account = relationship("Account")


class EscrowTransaction(Base):
    __tablename__ = "escrow_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_listings.id"), nullable=False)
    offer_id = Column(UUID(as_uuid=True), ForeignKey("offers.id"), nullable=False)
    buyer_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    amount = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    commission = Column(Numeric(20, 2))
    status = Column(SQLEnum(EscrowStatus), default=EscrowStatus.PENDING, nullable=False)
    stripe_payment_intent_id = Column(String(255))
    released_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    listing = relationship("MarketplaceListing")
    offer = relationship("Offer")
    buyer = relationship("Account", foreign_keys=[buyer_id])
    seller = relationship("Account", foreign_keys=[seller_id])

