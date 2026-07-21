import re

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from decimal import Decimal
from app.models.asset import (
    AssetType, CategoryGroup, AssetStatus, OwnershipType, Condition, ValuationType
)


# How far past "now" an acquisition_date may sit before we reject it. A client in a
# timezone ahead of UTC submits its own midnight-today, which is briefly in the future
# by UTC's reckoning; anything beyond a day is a genuine data-entry error.
ACQUISITION_DATE_FUTURE_TOLERANCE = timedelta(days=1)

_DATE_ONLY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class _AcquisitionDateGuard(BaseModel):
    """Normalizes acquisition_date and rejects future dates. Shared by
    AssetCreate/AssetUpdate."""

    # check_fields=False: the field is declared on the subclasses, not here.
    @field_validator("acquisition_date", mode="before", check_fields=False)
    @classmethod
    def _date_only_is_utc_midnight(cls, value: Any) -> Any:
        # A bare "2021-07-15" must not pick up the server's local timezone on
        # its way into a timestamptz column (it was persisting as
        # 2021-07-15 07:00:00+00 from a UTC-7 host): pin date-only input to
        # UTC midnight so the calendar date survives any later comparison.
        if isinstance(value, str) and _DATE_ONLY_RE.fullmatch(value.strip()):
            return datetime.strptime(value.strip(), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        if isinstance(value, date) and not isinstance(value, datetime):
            return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return value

    @field_validator("acquisition_date", check_fields=False)
    @classmethod
    def _reject_future_acquisition_date(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return value
        # Legacy clients may send naive datetimes; treat them as UTC so the
        # comparison below can never raise on naive-vs-aware — and persist the
        # aware value so the DB never re-interprets it in a local timezone.
        as_aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if as_aware > datetime.now(timezone.utc) + ACQUISITION_DATE_FUTURE_TOLERANCE:
            raise ValueError("Acquisition date cannot be in the future.")
        return as_aware


class AssetCreate(_AcquisitionDateGuard):
    # Category-based fields (new approach)
    category: Optional[str] = None  # Category name
    category_id: Optional[UUID] = None  # Category ID
    category_group: Optional[CategoryGroup] = None
    
    # Legacy field (for backward compatibility)
    asset_type: Optional[AssetType] = None
    
    # Basic information
    name: str
    symbol: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    
    # Values
    current_value: Optional[Decimal] = None
    estimated_value: Optional[Decimal] = None
    currency: str = "USD"
    
    # Status and metadata
    condition: Optional[Condition] = None
    ownership_type: Optional[OwnershipType] = None
    status: Optional[AssetStatus] = AssetStatus.ACTIVE
    
    # Dates
    acquisition_date: Optional[datetime] = None
    purchase_price: Optional[Decimal] = None
    
    # Category-specific fields (flexible JSON)
    specifications: Optional[Dict[str, Any]] = None
    
    # Valuation
    valuation_type: Optional[ValuationType] = ValuationType.MANUAL
    
    # Additional metadata
    metadata: Optional[Dict[str, Any]] = None
    
    # Photos and documents (URLs or UUIDs of already uploaded files)
    photos: Optional[List[str]] = None
    images: Optional[List[str]] = None  # Alias accepted alongside photos
    documents: Optional[List[str]] = None


class AssetUpdate(_AcquisitionDateGuard):
    # All fields from AssetCreate are optional for updates
    category: Optional[str] = None
    category_id: Optional[UUID] = None
    category_group: Optional[CategoryGroup] = None
    asset_type: Optional[AssetType] = None
    name: Optional[str] = None
    symbol: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    current_value: Optional[Decimal] = None
    estimated_value: Optional[Decimal] = None
    currency: Optional[str] = None
    condition: Optional[Condition] = None
    ownership_type: Optional[OwnershipType] = None
    status: Optional[AssetStatus] = None
    acquisition_date: Optional[datetime] = None
    purchase_price: Optional[Decimal] = None
    specifications: Optional[Dict[str, Any]] = None
    valuation_type: Optional[ValuationType] = None
    metadata: Optional[Dict[str, Any]] = None
    photos: Optional[List[UUID]] = None
    documents: Optional[List[UUID]] = None


class AssetResponse(BaseModel):
    id: UUID
    asset_code: Optional[str] = None  # Human-readable code shown to users (e.g. AK-01)
    category: Optional[str] = None  # Category name from relationship
    category_id: Optional[UUID] = None
    category_group: Optional[CategoryGroup] = None
    asset_type: Optional[AssetType] = None  # Legacy field
    name: str
    symbol: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    current_value: Decimal
    estimated_value: Optional[Decimal] = None
    currency: str
    status: AssetStatus
    condition: Optional[Condition] = None
    ownership_type: Optional[OwnershipType] = None
    acquisition_date: Optional[datetime] = None
    purchase_price: Optional[Decimal] = None
    last_appraisal_date: Optional[datetime] = None
    specifications: Optional[Dict[str, Any]] = None
    valuation_type: Optional[ValuationType] = None
    metadata: Optional[Dict[str, Any]] = Field(None, alias="meta_data")
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    # Computed fields (will be populated in response)
    image: Optional[str] = None  # Primary image URL
    images: Optional[List[str]] = None  # All image URLs
    last_updated: Optional[str] = None  # Human-readable format

    class Config:
        from_attributes = True

