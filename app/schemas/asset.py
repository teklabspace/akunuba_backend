from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from app.models.asset import (
    AssetType, CategoryGroup, AssetStatus, OwnershipType, Condition, ValuationType
)


class AssetCreate(BaseModel):
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
    
    # Photos and documents (URLs of already uploaded files - primary identifier)
    photos: Optional[List[str]] = None  # Array of public URLs
    documents: Optional[List[str]] = None  # Array of public URLs


class AssetUpdate(BaseModel):
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

