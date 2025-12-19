from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum


class AssetType(str, Enum):
    STOCK = "stock"
    BOND = "bond"
    REAL_ESTATE = "real_estate"
    LUXURY_ASSET = "luxury_asset"
    CRYPTO = "crypto"
    OTHER = "other"


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    asset_type = Column(SQLEnum(AssetType), nullable=False)
    name = Column(String(255), nullable=False)
    symbol = Column(String(50))
    description = Column(Text)
    current_value = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    meta_data = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account", back_populates="assets")
    valuations = relationship("AssetValuation", back_populates="asset")
    ownerships = relationship("AssetOwnership", back_populates="asset")


class AssetValuation(Base):
    __tablename__ = "asset_valuations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    value = Column(Numeric(20, 2), nullable=False)
    currency = Column(String(3), default="USD")
    valuation_method = Column(String(50))
    valuation_date = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    asset = relationship("Asset", back_populates="valuations")


class AssetOwnership(Base):
    __tablename__ = "asset_ownership"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    ownership_percentage = Column(Numeric(5, 2), default=100.00, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    asset = relationship("Asset", back_populates="ownerships")
    account = relationship("Account")

