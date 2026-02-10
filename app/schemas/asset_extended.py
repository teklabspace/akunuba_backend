from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from app.models.asset import (
    CategoryGroup, AppraisalType, AppraisalStatus, SaleRequestStatus,
    TransferStatus, TransferType, ReportType
)


# Category Schemas
class CategoryResponse(BaseModel):
    id: UUID
    name: str
    category_group: CategoryGroup
    description: Optional[str] = None
    icon_file: Optional[str] = None
    form_fields: Optional[List[str]] = None
    card_fields: Optional[List[str]] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CategoryGroupResponse(BaseModel):
    groups: List[str]


# Photo Schemas
class PhotoResponse(BaseModel):
    id: UUID
    url: str
    thumbnail_url: Optional[str] = None
    file_name: str
    file_size: Optional[int] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


class PhotoUploadResponse(BaseModel):
    data: PhotoResponse


# Document Schemas
class DocumentResponse(BaseModel):
    id: UUID
    name: str
    document_type: Optional[str] = None
    url: str
    date: Optional[datetime] = None
    file_size: Optional[int] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    data: List[DocumentResponse]


# Appraisal Schemas
class AppraisalRequest(BaseModel):
    appraisal_type: AppraisalType
    notes: Optional[str] = None
    preferred_date: Optional[datetime] = None


class AppraisalResponse(BaseModel):
    id: UUID
    asset_id: UUID
    appraisal_type: AppraisalType
    status: AppraisalStatus
    requested_at: datetime
    estimated_completion_date: Optional[datetime] = None
    estimated_cost: Optional[Decimal] = None
    completed_at: Optional[datetime] = None
    report_url: Optional[str] = None
    estimated_value: Optional[Decimal] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class AppraisalListResponse(BaseModel):
    data: List[AppraisalResponse]


# Sale Request Schemas
class SaleRequestCreate(BaseModel):
    target_price: Optional[Decimal] = None
    sale_note: Optional[str] = None
    preferred_sale_date: Optional[datetime] = None


class SaleRequestResponse(BaseModel):
    id: UUID
    asset_id: UUID
    target_price: Optional[Decimal] = None
    sale_note: Optional[str] = None
    status: SaleRequestStatus
    requested_at: datetime
    reviewed_at: Optional[datetime] = None
    message: Optional[str] = None
    potential_buyers: Optional[List[str]] = None

    class Config:
        from_attributes = True


class SaleRequestListResponse(BaseModel):
    data: List[SaleRequestResponse]


# Transfer Schemas
class TransferRequest(BaseModel):
    new_owner_email: str
    transfer_type: TransferType
    notes: Optional[str] = None


class TransferResponse(BaseModel):
    id: UUID
    asset_id: UUID
    new_owner_email: str
    transfer_type: TransferType
    status: TransferStatus
    notes: Optional[str] = None
    initiated_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Share Schemas
class ShareRequest(BaseModel):
    email: Optional[str] = None
    expires_in: Optional[int] = None  # days
    permissions: Optional[List[str]] = None


class ShareResponse(BaseModel):
    share_link: str
    expires_at: Optional[datetime] = None
    access_code: Optional[str] = None


# Report Schemas
class ReportRequest(BaseModel):
    report_type: ReportType
    include_documents: bool = False
    include_value_history: bool = False
    include_appraisals: bool = False


class ReportResponse(BaseModel):
    id: UUID
    report_url: Optional[str] = None
    report_type: ReportType
    generated_at: datetime
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Value History Schema
class ValueHistoryItem(BaseModel):
    date: datetime
    value: Decimal
    currency: str
    appraisal_id: Optional[UUID] = None
    appraisal_type: Optional[str] = None


class ValueHistoryResponse(BaseModel):
    data: List[ValueHistoryItem]


# Summary Schemas
class CategorySummary(BaseModel):
    category: str
    count: int
    total_value: Decimal


class CategoryGroupSummary(BaseModel):
    category_group: str
    count: int
    total_value: Decimal


class AssetsSummaryResponse(BaseModel):
    total_assets: int
    total_value: Decimal
    total_estimated_value: Decimal
    currency: str
    by_category: List[CategorySummary]
    by_category_group: List[CategoryGroupSummary]
    recently_added: int
    pending_appraisals: int
    pending_sales: int


# Value Trends Schema
class ValueTrendItem(BaseModel):
    date: datetime
    total_value: Decimal
    change: Decimal
    change_percent: Decimal


class ValueTrendsResponse(BaseModel):
    data: List[ValueTrendItem]


# Valuation Update Schema
class ValuationUpdate(BaseModel):
    current_value: Decimal
    estimated_value: Optional[Decimal] = None
    currency: str
    valuation_source: str  # "manual" or "appraisal"
    appraisal_id: Optional[UUID] = None
