from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, Text, Enum as SQLEnum, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid
from enum import Enum
from datetime import datetime


class AssetType(str, Enum):
    STOCK = "stock"
    BOND = "bond"
    REAL_ESTATE = "real_estate"
    LUXURY_ASSET = "luxury_asset"
    CRYPTO = "crypto"
    OTHER = "other"


class CategoryGroup(str, Enum):
    ASSETS = "Assets"
    PORTFOLIO = "Portfolio"
    LIABILITIES = "Liabilities"
    SHADOW_WEALTH = "Shadow Wealth"
    PHILANTHROPY = "Philanthropy"
    LIFESTYLE = "Lifestyle"
    GOVERNANCE = "Governance"


class AppraisalType(str, Enum):
    CONCIERGE = "Concierge"
    API = "API"
    STANDARD = "Standard"
    COMPREHENSIVE = "Comprehensive"
    EXPEDITED = "Expedited"
    INSURANCE = "Insurance"


class AppraisalStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SaleRequestStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class TransferStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TransferType(str, Enum):
    GIFT = "gift"
    SALE = "sale"
    INHERITANCE = "inheritance"


class ReportType(str, Enum):
    SUMMARY = "summary"
    DETAILED = "detailed"
    TAX = "tax"
    INSURANCE = "insurance"


class AssetStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    SOLD = "sold"
    INACTIVE = "inactive"


class OwnershipType(str, Enum):
    SOLE = "Sole"
    JOINT = "Joint"
    TRUST = "Trust"
    CORPORATE = "Corporate"


class Condition(str, Enum):
    EXCELLENT = "Excellent"
    VERY_GOOD = "Very Good"
    GOOD = "Good"
    FAIR = "Fair"
    POOR = "Poor"


class ValuationType(str, Enum):
    MANUAL = "manual"
    APPRAISAL = "appraisal"


# Custom TypeDecorator to ensure enum values (not names) are stored in database
# Works with PostgreSQL native enum types by converting enum members to values before binding
class EnumValueType(TypeDecorator):
    """TypeDecorator that stores enum values instead of names for PostgreSQL native enums"""
    impl = SQLEnum
    cache_ok = True
    
    def __init__(self, enum_class, length=50, *args, **kwargs):
        # Remove length from kwargs (not used by SQLEnum)
        kwargs.pop('length', None)
        # Use native_enum=True to work with PostgreSQL enum types
        # values_callable tells SQLAlchemy to use enum values in DDL
        super().__init__(
            enum_class,
            native_enum=True,
            values_callable=lambda x: [e.value for e in enum_class],
            *args,
            **kwargs
        )
        self.enum_class = enum_class
        self._value_to_member = {e.value: e for e in enum_class}
        self._name_to_member = {e.name: e for e in enum_class}
    
    def process_bind_param(self, value, dialect):
        """Convert enum member to its value when storing to database"""
        if value is None:
            return None
        if isinstance(value, self.enum_class):
            # Return the enum value (string) not the enum name
            # This is critical - SQLAlchemy will use this value when binding to the enum parameter
            return value.value
        if isinstance(value, str):
            # If it's already a string, check if it's a valid enum value
            if value in self._value_to_member:
                return value  # Already a valid value
            # Try to find enum member by name (e.g., "ACTIVE" -> "active")
            if value in self._name_to_member:
                return self._name_to_member[value].value
            # Try to create enum member from string (might be name or value)
            try:
                enum_member = self.enum_class(value)
                return enum_member.value
            except ValueError:
                # If string doesn't match, return as-is (might already be a value)
                return value
        return str(value) if value else None
    
    def process_result_value(self, value, dialect):
        """Convert database value back to enum member when reading"""
        if value is None:
            return None
        if isinstance(value, self.enum_class):
            return value
        # Try to find enum member by value
        if value in self._value_to_member:
            return self._value_to_member[value]
        # If not found, try to create from value
        try:
            return self.enum_class(value)
        except ValueError:
            return value


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    
    # Legacy field - kept for backward compatibility
    # Database expects UPPERCASE: 'STOCK', 'BOND', 'REAL_ESTATE', 'LUXURY_ASSET', 'CRYPTO', 'OTHER'
    # Python enum has lowercase values but uppercase names
    # Use a custom TypeDecorator to convert enum.name (uppercase) for database
    class AssetTypeEnumType(TypeDecorator):
        """TypeDecorator that stores enum names (uppercase) instead of values (lowercase) for assettype"""
        impl = SQLEnum
        cache_ok = True
        
        def __init__(self, *args, **kwargs):
            super().__init__(
                AssetType,
                native_enum=True,
                values_callable=lambda x: [e.name for e in AssetType],  # Use enum.name (uppercase)
                *args,
                **kwargs
            )
        
        def process_bind_param(self, value, dialect):
            """Convert enum member to its name (uppercase) when storing"""
            if value is None:
                return None
            if isinstance(value, AssetType):
                # Return the enum name (uppercase) not the value (lowercase)
                return value.name  # "OTHER" not "other"
            if isinstance(value, str):
                # If string, try to find enum and return its name
                try:
                    enum_member = AssetType(value.lower())  # Try by value
                    return enum_member.name
                except ValueError:
                    try:
                        enum_member = AssetType[value.upper()]  # Try by name
                        return enum_member.name
                    except KeyError:
                        return value.upper()  # Fallback to uppercase
            return str(value).upper() if value else None
        
        def process_result_value(self, value, dialect):
            """Convert database value (uppercase) back to enum member when reading"""
            if value is None:
                return None
            if isinstance(value, AssetType):
                return value
            # Database returns uppercase string, convert to enum
            try:
                return AssetType[value.upper()]
            except KeyError:
                return AssetType.OTHER  # Default fallback
    
    asset_type = Column(AssetTypeEnumType(), nullable=True)
    
    # Category-based fields
    category_id = Column(UUID(as_uuid=True), ForeignKey("asset_categories.id"), nullable=True)
    # EnumValueType ensures we use enum.value (not enum.name) when storing
    category_group = Column(EnumValueType(CategoryGroup, length=50), nullable=True)
    
    # Basic information
    name = Column(String(255), nullable=False)
    symbol = Column(String(50))
    description = Column(Text)
    location = Column(String(255))
    
    # Values
    current_value = Column(Numeric(20, 2), nullable=False)
    estimated_value = Column(Numeric(20, 2))
    currency = Column(String(3), default="USD", nullable=False)
    
    # Status and metadata
    # EnumValueType ensures we use enum.value (not enum.name) when storing
    status = Column(EnumValueType(AssetStatus, length=50), default=AssetStatus.ACTIVE, nullable=False)
    condition = Column(EnumValueType(Condition, length=50))
    ownership_type = Column(EnumValueType(OwnershipType, length=50))
    
    # Dates
    acquisition_date = Column(DateTime(timezone=True))
    purchase_price = Column(Numeric(20, 2))
    last_appraisal_date = Column(DateTime(timezone=True))
    
    # Category-specific fields stored in JSON
    specifications = Column(JSONB)  # Flexible storage for category-specific fields
    
    # Valuation
    valuation_type = Column(EnumValueType(ValuationType, length=50), default=ValuationType.MANUAL)
    
    # Additional metadata
    meta_data = Column("metadata", JSONB)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    account = relationship("Account", back_populates="assets")
    category = relationship("AssetCategory", foreign_keys=[category_id])
    valuations = relationship("AssetValuation", back_populates="asset", order_by="desc(AssetValuation.valuation_date)")
    ownerships = relationship("AssetOwnership", back_populates="asset", cascade="all, delete-orphan")
    photos = relationship("AssetPhoto", back_populates="asset", cascade="all, delete-orphan", order_by="AssetPhoto.is_primary.desc(), AssetPhoto.created_at")
    documents = relationship("AssetDocument", back_populates="asset", cascade="all, delete-orphan", order_by="desc(AssetDocument.created_at)")
    appraisals = relationship("AssetAppraisal", back_populates="asset", cascade="all, delete-orphan", order_by="desc(AssetAppraisal.requested_at)")
    sale_requests = relationship("AssetSaleRequest", back_populates="asset", cascade="all, delete-orphan")
    transfers = relationship("AssetTransfer", back_populates="asset", cascade="all, delete-orphan")
    shares = relationship("AssetShare", back_populates="asset", cascade="all, delete-orphan")
    reports = relationship("AssetReport", back_populates="asset", cascade="all, delete-orphan")


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


class AssetCategory(Base):
    __tablename__ = "asset_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    category_group = Column(EnumValueType(CategoryGroup, length=50), nullable=False)
    description = Column(Text)
    icon_file = Column(String(255))
    form_fields = Column(JSONB)  # Array of field names
    card_fields = Column(JSONB)  # Array of field names for card display
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AssetPhoto(Base):
    __tablename__ = "asset_photos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=True)  # Nullable to allow uploads before asset creation
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    mime_type = Column(String(100))
    url = Column(String(500), nullable=False)
    thumbnail_url = Column(String(500))
    supabase_storage_path = Column(String(500))
    is_primary = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    asset = relationship("Asset", back_populates="photos")


class AssetDocument(Base):
    __tablename__ = "asset_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=True)  # Nullable to allow uploads before asset creation
    name = Column(String(255), nullable=False)
    document_type = Column(String(100))  # e.g., "Purchase Agreement", "Insurance Documents"
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer)
    mime_type = Column(String(100))
    url = Column(String(500), nullable=False)
    supabase_storage_path = Column(String(500))
    date = Column(DateTime(timezone=True))  # Document date
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    asset = relationship("Asset", back_populates="documents")


class AssetAppraisal(Base):
    __tablename__ = "asset_appraisals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    appraisal_type = Column(EnumValueType(AppraisalType, length=50), nullable=False)
    status = Column(EnumValueType(AppraisalStatus, length=50), default=AppraisalStatus.PENDING, nullable=False)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    estimated_completion_date = Column(DateTime(timezone=True))
    estimated_cost = Column(Numeric(10, 2))
    completed_at = Column(DateTime(timezone=True))
    report_url = Column(String(500))
    estimated_value = Column(Numeric(20, 2))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    asset = relationship("Asset", back_populates="appraisals")


class AssetSaleRequest(Base):
    __tablename__ = "asset_sale_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    target_price = Column(Numeric(20, 2))
    sale_note = Column(Text)
    preferred_sale_date = Column(DateTime(timezone=True))
    status = Column(EnumValueType(SaleRequestStatus, length=50), default=SaleRequestStatus.PENDING, nullable=False)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True))
    message = Column(Text)
    potential_buyers = Column(JSONB)  # Array of buyer information
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    asset = relationship("Asset", back_populates="sale_requests")


class AssetTransfer(Base):
    __tablename__ = "asset_transfers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    new_owner_email = Column(String(255), nullable=False)
    transfer_type = Column(EnumValueType(TransferType, length=50), nullable=False)
    status = Column(EnumValueType(TransferStatus, length=50), default=TransferStatus.PENDING, nullable=False)
    notes = Column(Text)
    initiated_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    asset = relationship("Asset", back_populates="transfers")


class AssetShare(Base):
    __tablename__ = "asset_shares"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    share_link = Column(String(500), nullable=False, unique=True)
    access_code = Column(String(50))
    email = Column(String(255))
    expires_at = Column(DateTime(timezone=True))
    permissions = Column(JSONB)  # Array of permissions: ["view", "download"]
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    asset = relationship("Asset", back_populates="shares")


class AssetReport(Base):
    __tablename__ = "asset_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    report_type = Column(EnumValueType(ReportType, length=50), nullable=False)
    report_url = Column(String(500))
    include_documents = Column(Boolean, default=False)
    include_value_history = Column(Boolean, default=False)
    include_appraisals = Column(Boolean, default=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    asset = relationship("Asset", back_populates="reports")

