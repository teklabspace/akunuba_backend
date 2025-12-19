from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from app.models.asset import AssetType


class AssetCreate(BaseModel):
    asset_type: AssetType
    name: str
    symbol: Optional[str] = None
    description: Optional[str] = None
    current_value: Decimal
    currency: str = "USD"
    metadata: Optional[Dict[str, Any]] = None


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    current_value: Optional[Decimal] = None
    metadata: Optional[Dict[str, Any]] = None


class AssetResponse(BaseModel):
    id: UUID
    asset_type: AssetType
    name: str
    symbol: Optional[str] = None
    description: Optional[str] = None
    current_value: Decimal
    currency: str
    metadata: Optional[Dict[str, Any]] = Field(None, alias="meta_data")
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

