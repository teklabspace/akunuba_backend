from fastapi import APIRouter, Depends, HTTPException, status, Query, File, UploadFile, Form, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func as sql_func, func, desc, asc, inspect as sqlalchemy_inspect
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.asset import (
    Asset, AssetType, AssetValuation, AssetOwnership, AssetCategory, AssetPhoto,
    AssetDocument, AssetAppraisal, AssetSaleRequest, AssetTransfer, AssetShare,
    AssetReport, CategoryGroup, AppraisalType, AppraisalStatus, SaleRequestStatus,
    TransferStatus, TransferType, ReportType, AssetStatus, OwnershipType, Condition, ValuationType
)
from app.schemas.asset import AssetCreate, AssetUpdate, AssetResponse
from app.schemas.asset_extended import (
    CategoryResponse, CategoryGroupResponse, PhotoResponse, PhotoUploadResponse,
    DocumentResponse, DocumentListResponse, AppraisalRequest, AppraisalResponse,
    AppraisalListResponse, SaleRequestCreate, SaleRequestResponse, SaleRequestListResponse,
    TransferRequest, TransferResponse, ShareRequest, ShareResponse, ReportRequest,
    ReportResponse, ValueHistoryResponse, ValueHistoryItem, AssetsSummaryResponse,
    ValueTrendsResponse, ValueTrendItem, ValuationUpdate
)
from app.schemas.common import PaginatedResponse
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from app.api.deps import get_account, get_user_subscription_plan
from app.core.features import get_limit, check_usage_limit
from app.utils.logger import logger
from app.integrations.supabase_client import SupabaseClient
from app.config import settings
from uuid import UUID
from pydantic import BaseModel
import secrets

router = APIRouter()


def format_time_ago(dt: datetime) -> str:
    """Format datetime as human-readable time ago"""
    if not dt:
        return "Never"
    # Handle timezone-aware and naive datetimes
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - dt
    if delta.days > 0:
        return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
    elif delta.seconds >= 3600:
        hours = delta.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif delta.seconds >= 60:
        minutes = delta.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "Just now"


def build_asset_response(asset: Asset, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
    """Build asset response with computed fields"""
    # IMPORTANT: Only access relationships if they're already loaded (via selectinload)
    # Do NOT trigger lazy loading in async context - it will cause greenlet_spawn errors
    
    # Use SQLAlchemy inspect to check if relationships are loaded without triggering lazy load
    primary_photo = None
    all_images = []
    category_name = None
    documents_list = []
    
    try:
        inspector = sqlalchemy_inspect(asset)
        if inspector:
            # Check photos relationship state
            photos_state = inspector.attrs.get('photos')
            # Check if relationship is loaded (either as a list or as None)
            if photos_state is not None:
                # Check if relationship has been loaded (loaded_value can be None or a list)
                # If it's been loaded, loaded_value will be set (even if it's an empty list)
                # If it hasn't been loaded, loaded_value will be NEVER_SET or None depending on SQLAlchemy version
                from sqlalchemy.orm.state import NEVER_SET
                if hasattr(photos_state, 'loaded_value'):
                    # Relationship has been loaded
                    photos_list = photos_state.loaded_value
                    if photos_list is not None:
                        # Convert to list if needed
                        if not isinstance(photos_list, list):
                            photos_list = list(photos_list) if photos_list else []
                        # Process photos - ensure URLs are absolute
                        for photo in photos_list:
                            if photo and hasattr(photo, 'url') and photo.url:
                                url = photo.url
                                # Ensure URL is absolute (starts with http:// or https://)
                                if not url.startswith(('http://', 'https://')):
                                    # If URL is relative, try to get public URL from Supabase (images bucket)
                                    if hasattr(photo, 'supabase_storage_path') and photo.supabase_storage_path:
                                        try:
                                            url = SupabaseClient.get_file_url("images", photo.supabase_storage_path)
                                        except Exception as e:
                                            logger.warning(f"Failed to get public URL for photo {photo.id}: {e}")
                                            continue
                                    else:
                                        continue  # Skip if no valid URL
                                all_images.append(url)
                                if (hasattr(photo, 'is_primary') and photo.is_primary) or not primary_photo:
                                    primary_photo = photo
            
            # Check category relationship state
            category_state = inspector.attrs.get('category')
            if category_state:
                if hasattr(category_state, 'loaded_value') and category_state.loaded_value is not None:
                    category_obj = category_state.loaded_value
                    if category_obj and hasattr(category_obj, 'name'):
                        category_name = category_obj.name
            
            # Check documents relationship state
            documents_state = inspector.attrs.get('documents')
            if documents_state:
                if hasattr(documents_state, 'loaded_value') and documents_state.loaded_value is not None:
                    docs_list = documents_state.loaded_value
                    if not isinstance(docs_list, list):
                        docs_list = list(docs_list) if docs_list else []
                    documents_list = []
                    for doc in docs_list:
                        doc_url = doc.url if doc.url else None
                        # Ensure URL is absolute
                        if not doc_url or not doc_url.startswith(('http://', 'https://')):
                            # If URL is relative or missing, try to get public URL from Supabase
                            if hasattr(doc, 'supabase_storage_path') and doc.supabase_storage_path:
                                try:
                                    doc_url = SupabaseClient.get_file_url("documents", doc.supabase_storage_path)
                                except Exception as e:
                                    logger.warning(f"Failed to get public URL for document {doc.id}: {e}")
                                    doc_url = doc.url if doc.url else None
                        
                        documents_list.append({
                            "name": doc.name,
                            "url": doc_url,  # Public URL - primary identifier
                            "file_name": doc.file_name,
                            "document_type": doc.document_type,
                            "created_at": doc.created_at.isoformat() if doc.created_at else None
                        })
    except Exception as e:
        logger.warning(f"Error checking relationship states: {e}")
        # Continue without relationships if inspection fails
    
    # Fallback to specifications.image if no primary photo found
    primary_image_url = None
    if primary_photo and hasattr(primary_photo, 'url'):
        primary_image_url = primary_photo.url
        # Ensure URL is absolute
        if not primary_image_url.startswith(('http://', 'https://')):
            if hasattr(primary_photo, 'supabase_storage_path') and primary_photo.supabase_storage_path:
                try:
                    # Photos are stored in the 'images' bucket
                    primary_image_url = SupabaseClient.get_file_url("images", primary_photo.supabase_storage_path)
                except Exception as e:
                    logger.warning(f"Failed to get public URL for primary photo: {e}")
                    primary_image_url = all_images[0] if all_images else None
    elif not primary_image_url and asset.specifications:
        # Check if there's an image in specifications as fallback
        specs_image = asset.specifications.get('image') if isinstance(asset.specifications, dict) else None
        if specs_image and specs_image.strip() and specs_image.strip() not in ['', 'null', 'undefined']:
            # Ensure specifications image is absolute URL
            if specs_image.startswith(('http://', 'https://')):
                primary_image_url = specs_image
                # Also add to all_images if not already there
                if specs_image not in all_images:
                    all_images.insert(0, specs_image)  # Add as first item since it's the primary
    
    # Build response with safe access
    response_data = {
        "id": str(asset.id),
        "category": category_name,
        "category_id": str(asset.category_id) if asset.category_id else None,
        "category_group": asset.category_group.value if asset.category_group else None,
        "asset_type": asset.asset_type.name.lower() if asset.asset_type else None,  # Return lowercase value like "other"
        "name": asset.name,
        "symbol": asset.symbol,
        "description": asset.description,
        "location": asset.location,
        "current_value": float(asset.current_value),
        "estimated_value": float(asset.estimated_value) if asset.estimated_value else None,
        "currency": asset.currency,
        "status": asset.status.value if asset.status else None,
        "condition": asset.condition.value if asset.condition else None,
        "ownership_type": asset.ownership_type.value if asset.ownership_type else None,
        "acquisition_date": asset.acquisition_date.isoformat() if asset.acquisition_date else None,
        "purchase_price": float(asset.purchase_price) if asset.purchase_price else None,
        "last_appraisal_date": asset.last_appraisal_date.isoformat() if asset.last_appraisal_date else None,
        "specifications": asset.specifications or {},
        "valuation_type": asset.valuation_type.value if asset.valuation_type else None,
        "metadata": asset.meta_data or {},
        # Add documents array (only if already loaded)
        "documents": documents_list,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
        "image": primary_image_url,  # Use the primary image URL (from photos or specifications fallback)
        "images": all_images,  # All image URLs (from photos and potentially specifications)
        "last_updated": format_time_ago(asset.updated_at) if asset.updated_at else format_time_ago(asset.created_at) if asset.created_at else "Never"
    }
    return response_data


class ValuationResponse(BaseModel):
    id: UUID
    value: Decimal
    currency: str
    valuation_method: Optional[str]
    valuation_date: datetime
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class OwnershipResponse(BaseModel):
    id: UUID
    account_id: UUID
    ownership_percentage: Decimal
    created_at: datetime

    class Config:
        from_attributes = True


class AssetDetailResponse(AssetResponse):
    valuations: List[ValuationResponse] = []
    ownerships: List[OwnershipResponse] = []
    total_ownership_percentage: Decimal = Decimal("100.00")


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_asset(
    asset_data: AssetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new asset with category-based fields"""
    try:
        # Get user's account
        account = await get_account(current_user=current_user, db=db)
        plan = await get_user_subscription_plan(account=account, db=db)
        
        # Check usage limit
        assets_count = await db.execute(
            select(func.count(Asset.id)).where(Asset.account_id == account.id)
        )
        current_count = assets_count.scalar() or 0
        if not check_usage_limit(plan, "assets", current_count):
            limit = get_limit(plan, "assets")
            raise ForbiddenException(f"Asset limit reached. Maximum {limit} assets allowed for your plan.")
        
        # Resolve category if category name provided
        category_id = asset_data.category_id
        category_group_enum = None
        
        if asset_data.category and not category_id:
            # Try exact match first
            category_result = await db.execute(
                select(AssetCategory).where(AssetCategory.name == asset_data.category)
            )
            category = category_result.scalar_one_or_none()
            if not category:
                # Try case-insensitive match
                category_result = await db.execute(
                    select(AssetCategory).where(func.lower(AssetCategory.name) == asset_data.category.lower())
                )
                category = category_result.scalar_one_or_none()
            if category:
                category_id = category.id
                if not asset_data.category_group:
                    category_group_enum = category.category_group
                logger.info(f"Found category: {category.name} (ID: {category_id})")
            else:
                logger.warning(f"Category not found: {asset_data.category}")
        
        # Handle category_group - convert string to enum if needed
        # Database expects title case: "Assets", "Portfolio", "Governance", etc.
        if asset_data.category_group:
            if isinstance(asset_data.category_group, str):
                try:
                    # Try direct match first (frontend sends title case like "Assets")
                    category_group_enum = CategoryGroup(asset_data.category_group)
                except ValueError:
                    # Try case-insensitive match - map to correct title case enum values
                    category_group_lower = asset_data.category_group.lower()
                    
                    # Map common variations to enum values (all map to title case)
                    category_map = {
                        "governance": CategoryGroup.GOVERNANCE,  # "Governance"
                        "assets": CategoryGroup.ASSETS,  # "Assets"
                        "portfolio": CategoryGroup.PORTFOLIO,  # "Portfolio"
                        "liabilities": CategoryGroup.LIABILITIES,  # "Liabilities"
                        "shadow wealth": CategoryGroup.SHADOW_WEALTH,  # "Shadow Wealth"
                        "shadow_wealth": CategoryGroup.SHADOW_WEALTH,  # "Shadow Wealth"
                        "philanthropy": CategoryGroup.PHILANTHROPY,  # "Philanthropy"
                        "lifestyle": CategoryGroup.LIFESTYLE,  # "Lifestyle"
                    }
                    
                    if category_group_lower in category_map:
                        category_group_enum = category_map[category_group_lower]
                    else:
                        # Try to find by matching enum values (case-insensitive)
                        for enum_member in CategoryGroup:
                            if enum_member.value.lower() == category_group_lower:
                                category_group_enum = enum_member
                                break
                        else:
                            logger.warning(f"Invalid category_group: {asset_data.category_group}")
                            category_group_enum = None
            else:
                category_group_enum = asset_data.category_group
        
        # Determine asset_type if not provided (for backward compatibility)
        # Database enum expects UPPERCASE: 'STOCK', 'BOND', 'REAL_ESTATE', 'LUXURY_ASSET', 'CRYPTO', 'OTHER'
        # Python enum has lowercase values but uppercase names
        # AssetTypeEnumType will convert enum.name (uppercase) for database
        asset_type = asset_data.asset_type
        if not asset_type and category_group_enum:
            # Map category_group to asset_type if needed
            if category_group_enum == CategoryGroup.PORTFOLIO:
                asset_type = AssetType.STOCK
            elif category_group_enum == CategoryGroup.LIABILITIES:
                asset_type = AssetType.OTHER
            else:
                asset_type = AssetType.OTHER
        
        # Default to OTHER if still no asset_type
        if not asset_type:
            asset_type = AssetType.OTHER
        
        # Convert string to enum if needed
        # AssetTypeEnumType will handle conversion to uppercase name for database
        if isinstance(asset_type, str):
            try:
                # Try to match by value (lowercase)
                asset_type = AssetType(asset_type.lower())
            except ValueError:
                # Try to match by name (uppercase)
                try:
                    asset_type = AssetType[asset_type.upper()]
                except KeyError:
                    asset_type = AssetType.OTHER  # Default fallback
        
        # Ensure current_value is set
        current_value = asset_data.current_value or asset_data.estimated_value or Decimal("0.00")
        
        # Handle enum fields - ensure correct case for database
        # Database expects: status="active" (lowercase), condition="Excellent" (title case), etc.
        status_enum = asset_data.status
        if status_enum is None:
            status_enum = AssetStatus.ACTIVE
        elif isinstance(status_enum, str):
            # Convert string to enum - database expects lowercase: "active", "pending", "sold", "inactive"
            status_enum = status_enum.lower()
            try:
                status_enum = AssetStatus(status_enum)
            except ValueError:
                # Try title case if lowercase doesn't work
                status_enum = AssetStatus(status_enum.lower())
        
        condition_enum = asset_data.condition
        if condition_enum and isinstance(condition_enum, str):
            # Database expects title case: "Excellent", "Very Good", "Good", "Fair", "Poor"
            # Frontend sends title case, so try direct match first
            try:
                condition_enum = Condition(condition_enum)
            except ValueError:
                # Try case-insensitive match
                condition_lower = condition_enum.lower()
                for enum_member in Condition:
                    if enum_member.value.lower() == condition_lower:
                        condition_enum = enum_member
                        break
                else:
                    condition_enum = None
        
        ownership_type_enum = asset_data.ownership_type
        if ownership_type_enum and isinstance(ownership_type_enum, str):
            # Database expects title case: "Sole", "Joint", "Trust", "Corporate"
            try:
                ownership_type_enum = OwnershipType(ownership_type_enum)
            except ValueError:
                # Try case-insensitive match
                ownership_lower = ownership_type_enum.lower()
                for enum_member in OwnershipType:
                    if enum_member.value.lower() == ownership_lower:
                        ownership_type_enum = enum_member
                        break
                else:
                    ownership_type_enum = None
        
        valuation_type_enum = asset_data.valuation_type
        if valuation_type_enum is None:
            valuation_type_enum = ValuationType.MANUAL
        elif isinstance(valuation_type_enum, str):
            # Database expects lowercase: "manual", "appraisal"
            valuation_type_enum = valuation_type_enum.lower()
            try:
                valuation_type_enum = ValuationType(valuation_type_enum)
            except ValueError:
                valuation_type_enum = ValuationType.MANUAL
        
        # Handle metadata - convert string "null" to empty dict
        metadata = asset_data.metadata
        if metadata == "null" or metadata is None:
            metadata = {}
        
        # EnumValueType will automatically convert enum members to their values
        # So we can pass enum members directly - TypeDecorator handles the conversion
        asset = Asset(
            account_id=account.id,
            asset_type=asset_type,
            category_id=category_id,
            category_group=category_group_enum,
            name=asset_data.name,
            symbol=asset_data.symbol,
            description=asset_data.description,
            location=asset_data.location,
            current_value=current_value,
            estimated_value=asset_data.estimated_value,
            currency=asset_data.currency,
            status=status_enum,
            condition=condition_enum,
            ownership_type=ownership_type_enum,
            acquisition_date=asset_data.acquisition_date,
            purchase_price=asset_data.purchase_price,
            specifications=asset_data.specifications or {},
            valuation_type=valuation_type_enum,
            meta_data=metadata,
        )
        
        db.add(asset)
        await db.commit()
        await db.refresh(asset)
        
        # Load category relationship if category_id exists
        if asset.category_id:
            try:
                await db.refresh(asset, ["category"])
            except Exception:
                pass  # Category might not exist yet
        
        # Create initial valuation
        valuation = AssetValuation(
            asset_id=asset.id,
            value=current_value,
            currency=asset_data.currency,
            valuation_method="initial",
            valuation_date=datetime.now(timezone.utc),
        )
        db.add(valuation)
        
        # Create ownership record
        ownership = AssetOwnership(
            asset_id=asset.id,
            account_id=account.id,
            ownership_percentage=Decimal("100.00"),
        )
        db.add(ownership)
        
        # Link photos if provided (using URLs or IDs as identifiers)
        if asset_data.photos:
            for photo_ref in asset_data.photos:
                try:
                    photo = None
                    # First, try to treat the reference as a UUID (ID-based linking)
                    try:
                        from uuid import UUID as _UUID
                        photo_uuid = _UUID(str(photo_ref))
                        photo_result = await db.execute(
                            select(AssetPhoto).where(AssetPhoto.id == photo_uuid)
                        )
                        photo = photo_result.scalar_one_or_none()
                    except (ValueError, TypeError):
                        photo = None
                    
                    # If not a valid UUID or not found by ID, fall back to URL-based lookup
                    if not photo:
                        photo_url = str(photo_ref) if photo_ref is not None else None
                        if not photo_url:
                            continue
                        
                        # Normalize URL - remove trailing query params (e.g., "?") if present
                        normalized_url = photo_url.split('?')[0]
                        
                        # Look up photo by URL (primary identifier)
                        # Try exact match first, then try without query params
                        photo_result = await db.execute(
                            select(AssetPhoto).where(
                                or_(
                                    AssetPhoto.url == photo_url,
                                    AssetPhoto.url == normalized_url,
                                    AssetPhoto.url.like(f"{normalized_url}%")  # Match even if there are query params in DB
                                )
                            )
                        )
                        photo = photo_result.scalar_one_or_none()
                    
                    if photo:
                        photo.asset_id = asset.id
                    else:
                        logger.warning(f"Photo not found for reference: {photo_ref}")
                except Exception as e:
                    logger.warning(f"Failed to link photo with reference {photo_ref}: {e}")
        
        # Link documents if provided (using URLs or IDs as identifiers)
        if asset_data.documents:
            for doc_ref in asset_data.documents:
                try:
                    document = None
                    # First, try to treat the reference as a UUID (ID-based linking)
                    try:
                        from uuid import UUID as _UUID
                        doc_uuid = _UUID(str(doc_ref))
                        doc_result = await db.execute(
                            select(AssetDocument).where(AssetDocument.id == doc_uuid)
                        )
                        document = doc_result.scalar_one_or_none()
                    except (ValueError, TypeError):
                        document = None
                    
                    # If not a valid UUID or not found by ID, fall back to URL-based lookup
                    if not document:
                        doc_url = str(doc_ref) if doc_ref is not None else None
                        if not doc_url:
                            continue
                        
                        # Normalize URL - remove trailing query params (e.g., "?") if present
                        normalized_url = doc_url.split('?')[0]
                        
                        # Look up document by URL (primary identifier)
                        # Try exact match first, then try without query params
                        doc_result = await db.execute(
                            select(AssetDocument).where(
                                or_(
                                    AssetDocument.url == doc_url,
                                    AssetDocument.url == normalized_url,
                                    AssetDocument.url.like(f"{normalized_url}%")  # Match even if there are query params in DB
                                )
                            )
                        )
                        document = doc_result.scalar_one_or_none()
                    
                    if document:
                        document.asset_id = asset.id
                    else:
                        logger.warning(f"Document not found for reference: {doc_ref}")
                except Exception as e:
                    logger.warning(f"Failed to link document with reference {doc_ref}: {e}")
        
        await db.commit()
        
        # Reload asset with category relationship for response
        result = await db.execute(
            select(Asset)
            .options(selectinload(Asset.category))
            .where(Asset.id == asset.id)
        )
        asset = result.scalar_one()
        
        # Get category name
        category_name = None
        if asset.category_id:
            try:
                category_result = await db.execute(
                    select(AssetCategory).where(AssetCategory.id == asset.category_id)
                )
                category = category_result.scalar_one_or_none()
                if category:
                    category_name = category.name
            except Exception as e:
                logger.warning(f"Failed to load category: {e}")
        
        # Build minimal response as per ASSETS_CREATION_PAYLOAD.md specification
        response = {
            "id": str(asset.id),
            "name": asset.name,
            "category": category_name or asset_data.category,
            "category_group": asset.category_group.value if asset.category_group else asset_data.category_group.value if asset_data.category_group else None,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
        }
        
        logger.info(f"Asset created: {asset.id} for account {account.id}")
        return {"data": response}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating asset: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create asset: {str(e)}"
        )


@router.get("", response_model=Dict[str, Any])
async def list_assets(
    category: Optional[str] = Query(None, description="Filter by category name"),
    category_id: Optional[UUID] = Query(None, description="Filter by category ID"),
    category_group: Optional[CategoryGroup] = Query(None, description="Filter by category group"),
    asset_type: Optional[AssetType] = Query(None, description="Filter by asset type (legacy)"),
    search: Optional[str] = Query(None, description="Search by name or symbol"),
    min_value: Optional[Decimal] = Query(None, description="Minimum asset value"),
    max_value: Optional[Decimal] = Query(None, description="Maximum asset value"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    sort_by: Optional[str] = Query("created_at", description="Sort field (name, estimated_value, last_appraisal, created_at)"),
    order: Optional[str] = Query("desc", description="Sort order (asc or desc)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: Optional[int] = Query(None, ge=1, le=100, description="Items per page (alias for page_size)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List assets with pagination and filtering"""
    try:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()
        
        if not account:
            return {
                "data": [],
                "pagination": {
                    "page": page,
                    "limit": limit or page_size,
                    "total": 0,
                    "total_pages": 0
                }
            }
        
        # Use limit if provided, otherwise page_size
        items_per_page = limit or page_size
        
        # Build query with relationships
        query = select(Asset).options(
            selectinload(Asset.category),
            selectinload(Asset.photos),
            selectinload(Asset.documents)
        ).where(Asset.account_id == account.id)
        count_query = select(sql_func.count()).select_from(Asset).where(Asset.account_id == account.id)
        
        # Apply filters
        if category_id:
            query = query.where(Asset.category_id == category_id)
            count_query = count_query.where(Asset.category_id == category_id)
        elif category:
            # Try case-insensitive match
            category_result = await db.execute(
                select(AssetCategory).where(func.lower(AssetCategory.name) == category.lower())
            )
            cat = category_result.scalar_one_or_none()
            if cat:
                query = query.where(Asset.category_id == cat.id)
                count_query = count_query.where(Asset.category_id == cat.id)
        
        if category_group:
            query = query.where(Asset.category_group == category_group)
            count_query = count_query.where(Asset.category_group == category_group)
        
        if asset_type:  # Legacy support - handle AssetType enum
            # AssetType enum name is uppercase (STOCK, BOND, etc.) but we might get lowercase
            if isinstance(asset_type, str):
                try:
                    asset_type = AssetType[asset_type.upper()]
                except KeyError:
                    try:
                        asset_type = AssetType(asset_type.lower())
                    except ValueError:
                        asset_type = None
            if asset_type:
                query = query.where(Asset.asset_type == asset_type)
                count_query = count_query.where(Asset.asset_type == asset_type)
        
        if search:
            search_filter = or_(
                Asset.name.ilike(f"%{search}%"),
                Asset.symbol.ilike(f"%{search}%"),
                Asset.description.ilike(f"%{search}%")
            )
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)
        
        if min_value is not None:
            query = query.where(Asset.current_value >= min_value)
            count_query = count_query.where(Asset.current_value >= min_value)
        
        if max_value is not None:
            query = query.where(Asset.current_value <= max_value)
            count_query = count_query.where(Asset.current_value <= max_value)
        
        if currency:
            query = query.where(Asset.currency == currency.upper())
            count_query = count_query.where(Asset.currency == currency.upper())
        
        # Apply sorting - handle nullable columns by using nullsfirst/nullslast
        sort_column = Asset.created_at
        if sort_by == "name":
            sort_column = Asset.name
        elif sort_by == "estimated_value":
            sort_column = Asset.estimated_value
        elif sort_by == "last_appraisal":
            sort_column = Asset.last_appraisal_date
        elif sort_by == "created_at":
            sort_column = Asset.created_at
        
        # Normalize order parameter
        order_lower = (order or "desc").lower()
        if order_lower == "asc":
            # For nullable columns, put nulls last when ascending
            if sort_by in ["estimated_value", "last_appraisal"]:
                query = query.order_by(asc(sort_column).nulls_last())
            else:
                query = query.order_by(asc(sort_column))
        else:
            # For nullable columns, put nulls last when descending (most recent first)
            if sort_by in ["estimated_value", "last_appraisal"]:
                query = query.order_by(desc(sort_column).nulls_last())
            else:
                query = query.order_by(desc(sort_column))
        
        # Get total count
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0
        
        # Apply pagination
        offset = (page - 1) * items_per_page
        query = query.offset(offset).limit(items_per_page)
        
        # Execute query
        result = await db.execute(query)
        assets = result.scalars().all()
        
        # Calculate pages
        total_pages = (total + items_per_page - 1) // items_per_page if total > 0 else 0
        
        # Build response with computed fields
        # Note: relationships are already loaded via selectinload above
        asset_responses = []
        for asset in assets:
            try:
                asset_responses.append(build_asset_response(asset))
            except Exception as e:
                logger.error(f"Error building response for asset {asset.id}: {e}")
                # Fallback to basic response if relationship loading fails
                asset_responses.append({
                    "id": str(asset.id),
                    "name": asset.name,
                    "category": None,
                    "category_id": str(asset.category_id) if asset.category_id else None,
                    "category_group": asset.category_group.value if asset.category_group else None,
                    "asset_type": asset.asset_type.name.lower() if asset.asset_type else None,
                    "status": asset.status.value if asset.status else None,
                    "created_at": asset.created_at.isoformat() if asset.created_at else None,
                    "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
                })
        
        return {
            "data": asset_responses,
            "pagination": {
                "page": page,
                "limit": items_per_page,
                "total": total,
                "total_pages": total_pages
            }
        }
    except Exception as e:
        logger.error(f"Error listing assets: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list assets: {str(e)}"
        )


@router.get("/{asset_id}", response_model=Dict[str, Any])
async def get_asset(
    asset_id: UUID,
    include_valuations: bool = Query(True, description="Include valuation history"),
    include_ownership: bool = Query(True, description="Include ownership details"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get asset details with all frontend-required fields"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get asset with all relationships
    query = select(Asset).where(
        and_(Asset.id == asset_id, Asset.account_id == account.id)
    ).options(
        selectinload(Asset.category),
        selectinload(Asset.photos),
        selectinload(Asset.documents),
        selectinload(Asset.valuations),
        selectinload(Asset.ownerships),
        selectinload(Asset.appraisals)
    )
    
    result = await db.execute(query)
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Build base asset response
    response_dict = build_asset_response(asset)
    
    # Add status display
    status_display = {
        AssetStatus.ACTIVE: "Active Investment",
        AssetStatus.PENDING: "Pending",
        AssetStatus.SOLD: "Sold",
        AssetStatus.INACTIVE: "Inactive"
    }.get(asset.status, "Unknown")
    response_dict["status"] = status_display
    
    # Ensure images array has absolute URLs (CRITICAL for frontend)
    # Photos are loaded via selectinload, so we can safely access them
    images_array = []
    if asset.photos:
        for photo in asset.photos:
            if photo and hasattr(photo, 'url') and photo.url:
                # Ensure URL is absolute (starts with http:// or https://)
                url = photo.url
                if not url.startswith(('http://', 'https://')):
                    # If URL is relative, try to get public URL from Supabase (images bucket)
                    if hasattr(photo, 'supabase_storage_path') and photo.supabase_storage_path:
                        try:
                            url = SupabaseClient.get_file_url("images", photo.supabase_storage_path)
                        except Exception as e:
                            logger.warning(f"Failed to get public URL for photo {photo.id}: {e}")
                            continue
                    else:
                        continue  # Skip if no valid URL
                images_array.append(url)
    
    # Set images array (frontend expects this)
    response_dict["images"] = images_array
    
    # Set single image field (fallback for frontend)
    response_dict["image"] = images_array[0] if images_array else None
    
    # Add documents array with absolute URLs (CRITICAL for frontend)
    documents_list = []
    if asset.documents:
        for doc in asset.documents:
            # Ensure URL is absolute
            doc_url = doc.url if doc.url else None
            if not doc_url or not doc_url.startswith(('http://', 'https://')):
                # If URL is relative or missing, try to get public URL from Supabase
                if hasattr(doc, 'supabase_storage_path') and doc.supabase_storage_path:
                    try:
                        doc_url = SupabaseClient.get_file_url("documents", doc.supabase_storage_path)
                    except Exception as e:
                        logger.warning(f"Failed to get public URL for document {doc.id}: {e}")
                        doc_url = None
            
            documents_list.append({
                "name": doc.name,
                "url": doc_url,  # Public URL - primary identifier (absolute, accessible)
                "date": doc.date.isoformat() if doc.date else None,
                "type": doc.mime_type,
                "document_type": doc.document_type,
                "file_name": doc.file_name,
                "file_size": doc.file_size,
                "created_at": doc.created_at.isoformat() if doc.created_at else None
            })
    response_dict["documents"] = documents_list
    
    # Add value history for charts
    value_history = []
    if include_valuations and asset.valuations:
        for val in sorted(asset.valuations, key=lambda x: x.valuation_date):
            value_history.append({
                "date": val.valuation_date.isoformat(),
                "value": float(val.value),
                "currency": val.currency
            })
    response_dict["value_history"] = value_history
    
    # Calculate value change
    if asset.purchase_price and asset.current_value:
        value_change = ((asset.current_value - asset.purchase_price) / asset.purchase_price) * 100
        response_dict["value_change"] = f"{value_change:+.1f}%"
        response_dict["value_change_label"] = "Since Purchase"
    else:
        response_dict["value_change"] = None
        response_dict["value_change_label"] = None
    
    # Add ownership display
    if asset.ownerships:
        ownership_types = [o.ownership_percentage for o in asset.ownerships]
        if len(ownership_types) == 1 and ownership_types[0] == Decimal("100.00"):
            response_dict["ownership"] = "Sole Ownership"
        else:
            response_dict["ownership"] = "Joint Ownership"
    else:
        response_dict["ownership"] = "Sole Ownership"
    
    # Add category-specific fields from specifications
    if asset.specifications:
        # Extract common fields that might be in specifications
        if "property_type" in asset.specifications:
            response_dict["property_type"] = asset.specifications["property_type"]
        if "address" in asset.specifications:
            response_dict["address"] = asset.specifications["address"]
        if "size" in asset.specifications:
            response_dict["size"] = asset.specifications["size"]
        if "year_built" in asset.specifications:
            response_dict["year_built"] = asset.specifications["year_built"]
        if "monthly_rental_income" in asset.specifications:
            response_dict["monthly_rental_income"] = asset.specifications["monthly_rental_income"]
        if "annual_property_tax" in asset.specifications:
            response_dict["annual_property_tax"] = asset.specifications["annual_property_tax"]
        if "maintenance_costs" in asset.specifications:
            response_dict["maintenance_costs"] = asset.specifications["maintenance_costs"]
    
    # Add ownership details if requested
    if include_ownership:
        ownerships = [OwnershipResponse.model_validate(o).model_dump() for o in asset.ownerships]
        response_dict["ownerships"] = ownerships
        total_ownership = sum([o.ownership_percentage for o in asset.ownerships])
        response_dict["total_ownership_percentage"] = float(total_ownership)
    
    return {"data": response_dict}


@router.put("/{asset_id}", response_model=Dict[str, AssetResponse])
async def update_asset(
    asset_id: UUID,
    asset_data: AssetUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update an asset - all fields are optional"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Asset).where(
            and_(Asset.id == asset_id, Asset.account_id == account.id)
        )
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Update all provided fields
    if asset_data.category_id is not None:
        asset.category_id = asset_data.category_id
    if asset_data.category_group is not None:
        # Database expects title case: "Assets", "Portfolio", "Governance", etc.
        if isinstance(asset_data.category_group, str):
            try:
                asset.category_group = CategoryGroup(asset_data.category_group)
            except ValueError:
                # Try case-insensitive match
                category_lower = asset_data.category_group.lower()
                for enum_member in CategoryGroup:
                    if enum_member.value.lower() == category_lower:
                        asset.category_group = enum_member
                        break
        else:
            asset.category_group = asset_data.category_group
    if asset_data.name is not None:
        asset.name = asset_data.name
    if asset_data.symbol is not None:
        asset.symbol = asset_data.symbol
    if asset_data.description is not None:
        asset.description = asset_data.description
    if asset_data.location is not None:
        asset.location = asset_data.location
    if asset_data.current_value is not None:
        # Create new valuation if value changed
        if asset.current_value != asset_data.current_value:
            valuation = AssetValuation(
                asset_id=asset.id,
                value=asset_data.current_value,
                currency=asset.currency,
                valuation_method="manual_update",
                valuation_date=datetime.now(timezone.utc),
            )
            db.add(valuation)
        asset.current_value = asset_data.current_value
    if asset_data.estimated_value is not None:
        asset.estimated_value = asset_data.estimated_value
    if asset_data.currency is not None:
        asset.currency = asset_data.currency
    if asset_data.status is not None:
        # Database expects lowercase: "active", "pending", "sold", "inactive"
        if isinstance(asset_data.status, str):
            status_str = asset_data.status.lower()
            try:
                asset.status = AssetStatus(status_str)
            except ValueError:
                asset.status = AssetStatus.ACTIVE  # Default fallback
        else:
            asset.status = asset_data.status
    if asset_data.condition is not None:
        # Database expects title case: "Excellent", "Very Good", "Good", "Fair", "Poor"
        if isinstance(asset_data.condition, str):
            try:
                asset.condition = Condition(asset_data.condition)
            except ValueError:
                # Try case-insensitive match
                condition_lower = asset_data.condition.lower()
                for enum_member in Condition:
                    if enum_member.value.lower() == condition_lower:
                        asset.condition = enum_member
                        break
        else:
            asset.condition = asset_data.condition
    if asset_data.ownership_type is not None:
        # Database expects title case: "Sole", "Joint", "Trust", "Corporate"
        if isinstance(asset_data.ownership_type, str):
            try:
                asset.ownership_type = OwnershipType(asset_data.ownership_type)
            except ValueError:
                # Try case-insensitive match
                ownership_lower = asset_data.ownership_type.lower()
                for enum_member in OwnershipType:
                    if enum_member.value.lower() == ownership_lower:
                        asset.ownership_type = enum_member
                        break
        else:
            asset.ownership_type = asset_data.ownership_type
    if asset_data.acquisition_date is not None:
        asset.acquisition_date = asset_data.acquisition_date
    if asset_data.purchase_price is not None:
        asset.purchase_price = asset_data.purchase_price
    if asset_data.specifications is not None:
        asset.specifications = asset_data.specifications
    if asset_data.valuation_type is not None:
        # Database expects lowercase: "manual", "appraisal"
        if isinstance(asset_data.valuation_type, str):
            valuation_str = asset_data.valuation_type.lower()
            try:
                asset.valuation_type = ValuationType(valuation_str)
            except ValueError:
                asset.valuation_type = ValuationType.MANUAL  # Default fallback
        else:
            asset.valuation_type = asset_data.valuation_type
    if asset_data.metadata is not None:
        # Handle string "null" and convert to empty dict
        metadata = asset_data.metadata
        if metadata == "null" or metadata is None:
            metadata = {}
        asset.meta_data = metadata
    
    await db.commit()
    
    # Reload asset with all relationships using selectinload
    result = await db.execute(
        select(Asset)
        .options(
            selectinload(Asset.category),
            selectinload(Asset.photos),
            selectinload(Asset.documents)
        )
        .where(Asset.id == asset.id)
    )
    asset = result.scalar_one()
    
    response = build_asset_response(asset)
    
    logger.info(f"Asset updated: {asset.id}")
    return {"data": response}


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete an asset and its related data"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get asset with relationships to check for dependencies
    result = await db.execute(
        select(Asset).options(
            selectinload(Asset.valuations),
            selectinload(Asset.ownerships)
        ).where(
            and_(Asset.id == asset_id, Asset.account_id == account.id)
        )
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Check if asset is listed in marketplace
    from app.models.marketplace import MarketplaceListing, ListingStatus
    listing_result = await db.execute(
        select(MarketplaceListing).where(
            and_(
                MarketplaceListing.asset_id == asset_id,
                MarketplaceListing.status.in_([ListingStatus.PENDING_APPROVAL, ListingStatus.APPROVED, ListingStatus.ACTIVE])
            )
        )
    )
    if listing_result.scalar_one_or_none():
        raise BadRequestException("Cannot delete asset that is listed in marketplace")
    
    # Delete related valuations
    if asset.valuations:
        for valuation in asset.valuations:
            await db.delete(valuation)
    
    # Delete related ownerships
    if asset.ownerships:
        for ownership in asset.ownerships:
            await db.delete(ownership)
    
    # Delete asset
    await db.delete(asset)
    await db.commit()
    
    logger.info(f"Asset deleted: {asset_id}")
    return None


class ValuationCreate(BaseModel):
    value: Decimal
    currency: str = "USD"
    valuation_method: Optional[str] = None
    notes: Optional[str] = None
    valuation_date: Optional[datetime] = None


@router.post("/{asset_id}/valuations", response_model=Dict[str, ValuationResponse], status_code=status.HTTP_201_CREATED)
async def create_valuation(
    asset_id: UUID,
    valuation_data: ValuationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(Asset).where(
            and_(Asset.id == asset_id, Asset.account_id == account.id)
        )
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    valuation = AssetValuation(
        asset_id=asset.id,
        value=valuation_data.value,
        currency=valuation_data.currency,
        valuation_method=valuation_data.valuation_method or "manual",
        valuation_date=valuation_data.valuation_date or datetime.utcnow(),
        notes=valuation_data.notes,
    )
    
    # Update asset current value
    asset.current_value = valuation_data.value
    asset.currency = valuation_data.currency
    
    db.add(valuation)
    await db.commit()
    await db.refresh(valuation)
    
    logger.info(f"Valuation created for asset {asset_id}")
    return {"data": ValuationResponse.model_validate(valuation)}


@router.get("/{asset_id}/valuations", response_model=Dict[str, List[ValuationResponse]])
async def get_asset_valuations(
    asset_id: UUID,
    limit: int = Query(50, ge=1, le=100, description="Maximum number of valuations to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get valuation history for an asset"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(
            and_(Asset.id == asset_id, Asset.account_id == account.id)
        )
    )
    asset = asset_result.scalar_one_or_none()
    
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get valuations ordered by date
    result = await db.execute(
        select(AssetValuation)
        .where(AssetValuation.asset_id == asset_id)
        .order_by(desc(AssetValuation.valuation_date))
        .limit(limit)
    )
    valuations = result.scalars().all()
    
    return {"data": [ValuationResponse.model_validate(v) for v in valuations]}


@router.get("/{asset_id}/ownership", response_model=List[OwnershipResponse])
async def get_asset_ownership(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get ownership details for an asset"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify asset belongs to account or user has joint ownership
    asset_result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    asset = asset_result.scalar_one_or_none()
    
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Check if user owns the asset or has joint ownership
    ownership_check = await db.execute(
        select(AssetOwnership).where(
            and_(
                AssetOwnership.asset_id == asset_id,
                AssetOwnership.account_id == account.id
            )
        )
    )
    user_ownership = ownership_check.scalar_one_or_none()
    
    if asset.account_id != account.id and not user_ownership:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get all ownerships
    result = await db.execute(
        select(AssetOwnership)
        .where(AssetOwnership.asset_id == asset_id)
        .order_by(desc(AssetOwnership.ownership_percentage))
    )
    ownerships = result.scalars().all()
    
    return [OwnershipResponse.model_validate(o) for o in ownerships]


@router.post("/{asset_id}/ownership", response_model=OwnershipResponse, status_code=status.HTTP_201_CREATED)
async def add_joint_ownership(
    asset_id: UUID,
    joint_account_id: UUID,
    ownership_percentage: Decimal = Query(..., ge=Decimal("0.01"), le=Decimal("100.00")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add joint ownership to an asset"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify asset belongs to account
    result = await db.execute(
        select(Asset).where(
            and_(Asset.id == asset_id, Asset.account_id == account.id)
        )
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Verify joint account exists
    joint_account_result = await db.execute(
        select(Account).where(Account.id == joint_account_id)
    )
    joint_account = joint_account_result.scalar_one_or_none()
    
    if not joint_account:
        raise NotFoundException("Account", str(joint_account_id))
    
    # Check if ownership already exists
    existing_result = await db.execute(
        select(AssetOwnership).where(
            and_(
                AssetOwnership.asset_id == asset_id,
                AssetOwnership.account_id == joint_account_id
            )
        )
    )
    if existing_result.scalar_one_or_none():
        raise BadRequestException("Ownership already exists for this account")
    
    # Check total ownership doesn't exceed 100%
    existing_ownerships = await db.execute(
        select(AssetOwnership).where(AssetOwnership.asset_id == asset_id)
    )
    total_percentage = sum(
        [own.ownership_percentage for own in existing_ownerships.scalars().all()]
    )
    
    if total_percentage + ownership_percentage > Decimal("100.00"):
        raise BadRequestException(
            f"Total ownership percentage cannot exceed 100%. Current total: {total_percentage}%"
        )
    
    ownership = AssetOwnership(
        asset_id=asset.id,
        account_id=joint_account_id,
        ownership_percentage=ownership_percentage,
    )
    
    db.add(ownership)
    await db.commit()
    await db.refresh(ownership)
    
    logger.info(f"Joint ownership added for asset {asset_id}: {joint_account_id} ({ownership_percentage}%)")
    return OwnershipResponse.model_validate(ownership)


@router.delete("/{asset_id}/ownership/{ownership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_joint_ownership(
    asset_id: UUID,
    ownership_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove joint ownership from an asset"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(
            and_(Asset.id == asset_id, Asset.account_id == account.id)
        )
    )
    asset = asset_result.scalar_one_or_none()
    
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get ownership
    ownership_result = await db.execute(
        select(AssetOwnership).where(
            and_(
                AssetOwnership.id == ownership_id,
                AssetOwnership.asset_id == asset_id
            )
        )
    )
    ownership = ownership_result.scalar_one_or_none()
    
    if not ownership:
        raise NotFoundException("Ownership", str(ownership_id))
    
    # Cannot remove primary ownership (100%)
    if ownership.ownership_percentage >= Decimal("100.00"):
        raise BadRequestException("Cannot remove primary ownership")
    
    await db.delete(ownership)
    await db.commit()
    
    logger.info(f"Joint ownership removed: {ownership_id}")
    return None


@router.get("/summary/stats", response_model=Dict[str, Any])
async def get_asset_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get asset statistics summary"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get all assets
    assets_result = await db.execute(
        select(Asset).where(Asset.account_id == account.id)
    )
    assets = assets_result.scalars().all()
    
    if not assets:
        return {
            "total_assets": 0,
            "total_value": Decimal("0.00"),
            "by_type": {},
            "by_currency": {},
            "average_value": Decimal("0.00"),
            "min_value": Decimal("0.00"),
            "max_value": Decimal("0.00")
        }
    
    # Calculate statistics
    total_value = sum([asset.current_value for asset in assets])
    by_type = {}
    by_currency = {}
    
    for asset in assets:
        # By type
        asset_type = asset.asset_type.value
        if asset_type not in by_type:
            by_type[asset_type] = {"count": 0, "value": Decimal("0.00")}
        by_type[asset_type]["count"] += 1
        by_type[asset_type]["value"] += asset.current_value
        
        # By currency
        currency = asset.currency
        if currency not in by_currency:
            by_currency[currency] = {"count": 0, "value": Decimal("0.00")}
        by_currency[currency]["count"] += 1
        by_currency[currency]["value"] += asset.current_value
    
    values = [asset.current_value for asset in assets]
    
    return {
        "total_assets": len(assets),
        "total_value": float(total_value),
        "by_type": {k: {"count": v["count"], "value": float(v["value"])} for k, v in by_type.items()},
        "by_currency": {k: {"count": v["count"], "value": float(v["value"])} for k, v in by_currency.items()},
        "average_value": float(total_value / len(assets)),
        "min_value": float(min(values)),
        "max_value": float(max(values))
    }


# ==================== CATEGORIES ====================

@router.get("/categories", response_model=Dict[str, List[CategoryResponse]])
async def get_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all available asset categories"""
    result = await db.execute(
        select(AssetCategory).where(AssetCategory.is_active == True)
    )
    categories = result.scalars().all()
    
    return {
        "data": [CategoryResponse.model_validate(c) for c in categories]
    }


@router.get("/category-groups", response_model=Dict[str, List[str]])
async def get_category_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all category groups"""
    groups = [group.value for group in CategoryGroup]
    return {"data": groups}


# ==================== PHOTOS ====================

@router.post("/{asset_id}/photos", response_model=PhotoUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_asset_photo(
    asset_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload a photo for an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise BadRequestException("File must be an image")
    
    # Read file
    file_data = await file.read()
    file_size = len(file_data)
    
    if file_size > settings.MAX_UPLOAD_SIZE:
        raise BadRequestException(f"File size exceeds maximum allowed size")
    
    # Upload to Supabase - photos go to 'images' bucket
    file_path = f"assets/{asset_id}/photos/{file.filename}"
    try:
        SupabaseClient.upload_file(
            bucket="images",
            file_path=file_path,
            file_data=file_data,
            content_type=file.content_type
        )
        url = SupabaseClient.get_file_url("images", file_path)
    except Exception as e:
        logger.error(f"Failed to upload photo: {e}")
        raise BadRequestException("Failed to upload photo")
    
    # Create photo record
    photo = AssetPhoto(
        asset_id=asset.id,
        file_name=file.filename,
        file_path=file_path,
        file_size=file_size,
        mime_type=file.content_type,
        url=url,
        supabase_storage_path=file_path,
        is_primary=False
    )
    
    db.add(photo)
    await db.commit()
    await db.refresh(photo)
    
    logger.info(f"Photo uploaded for asset {asset_id}: {photo.id}")
    return PhotoUploadResponse(data=PhotoResponse.model_validate(photo))


@router.delete("/{asset_id}/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset_photo(
    asset_id: UUID,
    photo_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a photo from an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get photo
    photo_result = await db.execute(
        select(AssetPhoto).where(and_(AssetPhoto.id == photo_id, AssetPhoto.asset_id == asset_id))
    )
    photo = photo_result.scalar_one_or_none()
    if not photo:
        raise NotFoundException("Photo", str(photo_id))
    
    # Delete from storage - photos are in 'images' bucket
    if photo.supabase_storage_path:
        # Determine bucket from URL if available, otherwise default to 'images'
        bucket = "images"
        if photo.url and "/storage/v1/object/public/" in photo.url:
            # Extract bucket from URL: .../storage/v1/object/public/{bucket}/...
            parts = photo.url.split("/storage/v1/object/public/")
            if len(parts) > 1:
                bucket_from_url = parts[1].split("/")[0]
                if bucket_from_url in ["images", "documents"]:
                    bucket = bucket_from_url
        SupabaseClient.delete_file(bucket, photo.supabase_storage_path)
    
    await db.delete(photo)
    await db.commit()
    
    logger.info(f"Photo deleted: {photo_id}")
    return None


# ==================== DOCUMENTS ====================

@router.post("/{asset_id}/documents", response_model=Dict[str, DocumentResponse], status_code=status.HTTP_201_CREATED)
async def upload_asset_document(
    asset_id: UUID,
    file: UploadFile = File(...),
    document_type: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload a document for an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Validate file type
    file_extension = file.filename.split(".")[-1].lower() if "." in file.filename else ""
    if file_extension not in ["pdf", "doc", "docx"]:
        raise BadRequestException("File must be a PDF or document")
    
    # Read file
    file_data = await file.read()
    file_size = len(file_data)
    
    if file_size > settings.MAX_UPLOAD_SIZE:
        raise BadRequestException(f"File size exceeds maximum allowed size")
    
    # Upload to Supabase
    file_path = f"assets/{asset_id}/documents/{file.filename}"
    try:
        SupabaseClient.upload_file(
            bucket="documents",
            file_path=file_path,
            file_data=file_data,
            content_type=file.content_type or "application/pdf"
        )
        url = SupabaseClient.get_file_url("documents", file_path)
    except Exception as e:
        logger.error(f"Failed to upload document: {e}")
        raise BadRequestException("Failed to upload document")
    
    # Create document record
    document = AssetDocument(
        asset_id=asset.id,
        name=file.filename,
        document_type=document_type,
        file_name=file.filename,
        file_path=file_path,
        file_size=file_size,
        mime_type=file.content_type,
        url=url,
        supabase_storage_path=file_path,
        date=datetime.utcnow()
    )
    
    db.add(document)
    await db.commit()
    await db.refresh(document)
    
    logger.info(f"Document uploaded for asset {asset_id}: {document.id}")
    return {"data": DocumentResponse.model_validate(document)}


@router.get("/{asset_id}/documents", response_model=DocumentListResponse)
async def get_asset_documents(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all documents for an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get documents
    result = await db.execute(
        select(AssetDocument).where(AssetDocument.asset_id == asset_id).order_by(desc(AssetDocument.created_at))
    )
    documents = result.scalars().all()
    
    # Ensure all document URLs are absolute (CRITICAL for frontend)
    # Return only URLs, no IDs - URLs are the primary identifier
    documents_data = []
    for doc in documents:
        # Ensure URL is absolute
        doc_url = doc.url if doc.url else None
        if not doc_url or not doc_url.startswith(('http://', 'https://')):
            # If URL is relative or missing, try to get public URL from Supabase
            if hasattr(doc, 'supabase_storage_path') and doc.supabase_storage_path:
                try:
                    doc_url = SupabaseClient.get_file_url("documents", doc.supabase_storage_path)
                except Exception as e:
                    logger.warning(f"Failed to get public URL for document {doc.id}: {e}")
                    doc_url = doc.url if doc.url else None
        
        # Return only URL and metadata - NO ID
        documents_data.append({
            "name": doc.name,
            "url": doc_url,  # Public URL - primary identifier
            "file_name": doc.file_name,
            "document_type": doc.document_type,
            "file_size": doc.file_size if hasattr(doc, 'file_size') else None,
            "type": doc.mime_type if hasattr(doc, 'mime_type') else None,
            "date": doc.date.isoformat() if hasattr(doc, 'date') and doc.date else None,
            "created_at": doc.created_at.isoformat() if doc.created_at else None
        })
    
    return DocumentListResponse(data=documents_data)


@router.delete("/{asset_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset_document(
    asset_id: UUID,
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a document from an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get document
    doc_result = await db.execute(
        select(AssetDocument).where(and_(AssetDocument.id == document_id, AssetDocument.asset_id == asset_id))
    )
    document = doc_result.scalar_one_or_none()
    if not document:
        raise NotFoundException("Document", str(document_id))
    
    # Delete from storage
    if document.supabase_storage_path:
        SupabaseClient.delete_file("documents", document.supabase_storage_path)
    
    await db.delete(document)
    await db.commit()
    
    logger.info(f"Document deleted: {document_id}")
    return None


# ==================== VALUE HISTORY ====================

@router.get("/{asset_id}/value-history", response_model=ValueHistoryResponse)
async def get_asset_value_history(
    asset_id: UUID,
    start_date: Optional[datetime] = Query(None, description="Start date for history"),
    end_date: Optional[datetime] = Query(None, description="End date for history"),
    period: Optional[str] = Query(None, description="Time period (daily, weekly, monthly, yearly)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get value history for an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Build query
    query = select(AssetValuation).where(AssetValuation.asset_id == asset_id)
    
    if start_date:
        query = query.where(AssetValuation.valuation_date >= start_date)
    if end_date:
        query = query.where(AssetValuation.valuation_date <= end_date)
    
    query = query.order_by(asc(AssetValuation.valuation_date))
    
    result = await db.execute(query)
    valuations = result.scalars().all()
    
    # Get appraisals for additional context
    appraisals_result = await db.execute(
        select(AssetAppraisal).where(
            and_(
                AssetAppraisal.asset_id == asset_id,
                AssetAppraisal.status == AppraisalStatus.COMPLETED,
                AssetAppraisal.estimated_value.isnot(None)
            )
        )
    )
    appraisals = appraisals_result.scalars().all()
    
    # Build history items
    history_items = []
    for val in valuations:
        # Find related appraisal if any
        appraisal = next((a for a in appraisals if a.completed_at and abs((a.completed_at - val.valuation_date).total_seconds()) < 86400), None)
        
        history_items.append(ValueHistoryItem(
            date=val.valuation_date,
            value=val.value,
            currency=val.currency,
            appraisal_id=appraisal.id if appraisal else None,
            appraisal_type=appraisal.appraisal_type.value if appraisal else None
        ))
    
    return ValueHistoryResponse(data=history_items)


# ==================== APPRAISALS ====================

@router.post("/{asset_id}/appraisals", response_model=Dict[str, AppraisalResponse], status_code=status.HTTP_201_CREATED)
async def request_asset_appraisal(
    asset_id: UUID,
    appraisal_data: AppraisalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Request an appraisal for an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Create appraisal request
    appraisal = AssetAppraisal(
        asset_id=asset.id,
        appraisal_type=appraisal_data.appraisal_type,
        status=AppraisalStatus.PENDING,
        notes=appraisal_data.notes,
        estimated_completion_date=appraisal_data.preferred_date
    )
    
    db.add(appraisal)
    await db.commit()
    await db.refresh(appraisal)
    
    logger.info(f"Appraisal requested for asset {asset_id}: {appraisal.id}")
    return {"data": AppraisalResponse.model_validate(appraisal)}


@router.get("/{asset_id}/appraisals", response_model=AppraisalListResponse)
async def get_asset_appraisals(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all appraisals for an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get appraisals
    result = await db.execute(
        select(AssetAppraisal).where(AssetAppraisal.asset_id == asset_id).order_by(desc(AssetAppraisal.requested_at))
    )
    appraisals = result.scalars().all()
    
    return AppraisalListResponse(data=[AppraisalResponse.model_validate(a) for a in appraisals])


@router.get("/{asset_id}/appraisals/{appraisal_id}", response_model=Dict[str, AppraisalResponse])
async def get_appraisal_status(
    asset_id: UUID,
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get status of an appraisal request"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get appraisal
    appraisal_result = await db.execute(
        select(AssetAppraisal).where(
            and_(AssetAppraisal.id == appraisal_id, AssetAppraisal.asset_id == asset_id)
        )
    )
    appraisal = appraisal_result.scalar_one_or_none()
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    
    return {"data": AppraisalResponse.model_validate(appraisal)}


@router.patch("/{asset_id}/valuation", response_model=AssetResponse)
async def update_asset_valuation(
    asset_id: UUID,
    valuation_data: ValuationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update asset valuation"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Update asset value
    asset.current_value = valuation_data.current_value
    asset.currency = valuation_data.currency
    
    # Create valuation record
    valuation = AssetValuation(
        asset_id=asset.id,
        value=valuation_data.current_value,
        currency=valuation_data.currency,
        valuation_method=valuation_data.valuation_source,
        valuation_date=datetime.utcnow()
    )
    
    # If from appraisal, link it
    if valuation_data.appraisal_id:
        appraisal_result = await db.execute(
            select(AssetAppraisal).where(AssetAppraisal.id == valuation_data.appraisal_id)
        )
        appraisal = appraisal_result.scalar_one_or_none()
        if appraisal:
            valuation.notes = f"From appraisal: {appraisal.appraisal_type.value}"
    
    db.add(valuation)
    await db.commit()
    await db.refresh(asset)
    
    logger.info(f"Valuation updated for asset {asset_id}")
    return AssetResponse.model_validate(asset)


# ==================== SALE REQUESTS ====================

@router.post("/{asset_id}/sale-requests", response_model=Dict[str, SaleRequestResponse], status_code=status.HTTP_201_CREATED)
async def request_asset_sale(
    asset_id: UUID,
    sale_data: SaleRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Submit a request to sell an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Create sale request
    sale_request = AssetSaleRequest(
        asset_id=asset.id,
        target_price=sale_data.target_price,
        sale_note=sale_data.sale_note,
        preferred_sale_date=sale_data.preferred_sale_date,
        status=SaleRequestStatus.PENDING
    )
    
    db.add(sale_request)
    await db.commit()
    await db.refresh(sale_request)
    
    logger.info(f"Sale request created for asset {asset_id}: {sale_request.id}")
    return {"data": SaleRequestResponse.model_validate(sale_request)}


@router.get("/{asset_id}/sale-requests", response_model=SaleRequestListResponse)
async def get_asset_sale_requests(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all sale requests for an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get sale requests
    result = await db.execute(
        select(AssetSaleRequest).where(AssetSaleRequest.asset_id == asset_id).order_by(desc(AssetSaleRequest.requested_at))
    )
    sale_requests = result.scalars().all()
    
    return SaleRequestListResponse(data=[SaleRequestResponse.model_validate(sr) for sr in sale_requests])


@router.get("/{asset_id}/sale-requests/{request_id}", response_model=Dict[str, SaleRequestResponse])
async def get_sale_request_status(
    asset_id: UUID,
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get status of a sale request"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get sale request
    request_result = await db.execute(
        select(AssetSaleRequest).where(
            and_(AssetSaleRequest.id == request_id, AssetSaleRequest.asset_id == asset_id)
        )
    )
    sale_request = request_result.scalar_one_or_none()
    if not sale_request:
        raise NotFoundException("Sale Request", str(request_id))
    
    return {"data": SaleRequestResponse.model_validate(sale_request)}


@router.delete("/{asset_id}/sale-requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_sale_request(
    asset_id: UUID,
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel a pending sale request"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get sale request
    request_result = await db.execute(
        select(AssetSaleRequest).where(
            and_(AssetSaleRequest.id == request_id, AssetSaleRequest.asset_id == asset_id)
        )
    )
    sale_request = request_result.scalar_one_or_none()
    if not sale_request:
        raise NotFoundException("Sale Request", str(request_id))
    
    if sale_request.status != SaleRequestStatus.PENDING:
        raise BadRequestException("Only pending sale requests can be cancelled")
    
    await db.delete(sale_request)
    await db.commit()
    
    logger.info(f"Sale request cancelled: {request_id}")
    return None


# ==================== ASSET ACTIONS ====================

@router.post("/{asset_id}/transfer", response_model=Dict[str, TransferResponse], status_code=status.HTTP_201_CREATED)
async def transfer_asset_ownership(
    asset_id: UUID,
    transfer_data: TransferRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Transfer asset ownership to a new owner.
    
    Security Requirements:
    - New owner must be a registered user on the platform
    - Asset will be removed from current owner and transferred to new owner
    - All ownership records are updated accordingly
    """
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # SECURITY: Verify new owner email belongs to a registered user
    new_owner_result = await db.execute(
        select(User).where(
            and_(
                User.email == transfer_data.new_owner_email.lower().strip(),
                User.is_active == True  # Must be active user
            )
        )
    )
    new_owner = new_owner_result.scalar_one_or_none()
    
    if not new_owner:
        raise BadRequestException(
            f"New owner email '{transfer_data.new_owner_email}' is not registered or not active on this platform. "
            "The recipient must have an active account to receive asset transfers."
        )
    
    # Get new owner's account
    new_owner_account_result = await db.execute(
        select(Account).where(Account.user_id == new_owner.id)
    )
    new_owner_account = new_owner_account_result.scalar_one_or_none()
    
    if not new_owner_account:
        raise BadRequestException(
            f"New owner does not have an account. Please contact support."
        )
    
    # Prevent transferring to yourself
    if new_owner_account.id == account.id:
        raise BadRequestException("Cannot transfer asset to yourself")
    
    # Check if asset is listed in marketplace (prevent transfer of listed assets)
    from app.models.marketplace import MarketplaceListing, ListingStatus
    listing_result = await db.execute(
        select(MarketplaceListing).where(
            and_(
                MarketplaceListing.asset_id == asset_id,
                MarketplaceListing.status.in_([ListingStatus.PENDING_APPROVAL, ListingStatus.APPROVED, ListingStatus.ACTIVE])
            )
        )
    )
    if listing_result.scalar_one_or_none():
        raise BadRequestException("Cannot transfer asset that is currently listed in marketplace. Please remove listing first.")
    
    try:
        # Remove old ownership records (current owner)
        old_ownerships_result = await db.execute(
            select(AssetOwnership).where(AssetOwnership.asset_id == asset_id)
        )
        old_ownerships = old_ownerships_result.scalars().all()
        for old_ownership in old_ownerships:
            await db.delete(old_ownership)
        
        # Transfer asset to new owner (change account_id)
        asset.account_id = new_owner_account.id
        
        # Create new ownership record for new owner (100% ownership)
        new_ownership = AssetOwnership(
            asset_id=asset.id,
            account_id=new_owner_account.id,
            ownership_percentage=Decimal("100.00"),
        )
        db.add(new_ownership)
        
        # Create transfer record with COMPLETED status (since we're doing it immediately)
        transfer = AssetTransfer(
            asset_id=asset.id,
            new_owner_email=transfer_data.new_owner_email.lower().strip(),
            transfer_type=transfer_data.transfer_type,
            status=TransferStatus.COMPLETED,  # Completed immediately
            notes=transfer_data.notes,
            completed_at=datetime.now(timezone.utc)
        )
        db.add(transfer)
        
        await db.commit()
        await db.refresh(transfer)
        
        logger.info(
            f"Asset {asset_id} transferred from account {account.id} to account {new_owner_account.id} "
            f"(user: {new_owner.email}) via {transfer_data.transfer_type.value}"
        )
        
        return {"data": TransferResponse.model_validate(transfer)}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error transferring asset {asset_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to transfer asset: {str(e)}"
        )


@router.get("/{asset_id}/transfers", response_model=Dict[str, List[TransferResponse]])
async def get_asset_transfers(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all transfer history for an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account (or user has access)
    asset_result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Check if user owns the asset or has joint ownership
    ownership_check = await db.execute(
        select(AssetOwnership).where(
            and_(
                AssetOwnership.asset_id == asset_id,
                AssetOwnership.account_id == account.id
            )
        )
    )
    user_ownership = ownership_check.scalar_one_or_none()
    
    # Only allow viewing transfers if user owns the asset or is the original owner
    if asset.account_id != account.id and not user_ownership:
        raise ForbiddenException("You do not have permission to view transfers for this asset")
    
    # Get all transfers for this asset
    transfers_result = await db.execute(
        select(AssetTransfer)
        .where(AssetTransfer.asset_id == asset_id)
        .order_by(desc(AssetTransfer.initiated_at))
    )
    transfers = transfers_result.scalars().all()
    
    return {"data": [TransferResponse.model_validate(t) for t in transfers]}


@router.get("/{asset_id}/transfers/{transfer_id}", response_model=Dict[str, TransferResponse])
async def get_transfer_status(
    asset_id: UUID,
    transfer_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get status of a specific transfer"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account (or user has access)
    asset_result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Check if user owns the asset or has joint ownership
    ownership_check = await db.execute(
        select(AssetOwnership).where(
            and_(
                AssetOwnership.asset_id == asset_id,
                AssetOwnership.account_id == account.id
            )
        )
    )
    user_ownership = ownership_check.scalar_one_or_none()
    
    # Only allow viewing transfers if user owns the asset
    if asset.account_id != account.id and not user_ownership:
        raise ForbiddenException("You do not have permission to view this transfer")
    
    # Get transfer
    transfer_result = await db.execute(
        select(AssetTransfer).where(
            and_(
                AssetTransfer.id == transfer_id,
                AssetTransfer.asset_id == asset_id
            )
        )
    )
    transfer = transfer_result.scalar_one_or_none()
    if not transfer:
        raise NotFoundException("Transfer", str(transfer_id))
    
    return {"data": TransferResponse.model_validate(transfer)}


@router.delete("/{asset_id}/transfers/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_transfer(
    asset_id: UUID,
    transfer_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel a pending transfer (only if status is PENDING)"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get transfer
    transfer_result = await db.execute(
        select(AssetTransfer).where(
            and_(
                AssetTransfer.id == transfer_id,
                AssetTransfer.asset_id == asset_id
            )
        )
    )
    transfer = transfer_result.scalar_one_or_none()
    if not transfer:
        raise NotFoundException("Transfer", str(transfer_id))
    
    # Only allow cancelling pending transfers
    if transfer.status != TransferStatus.PENDING:
        raise BadRequestException("Only pending transfers can be cancelled")
    
    # Update transfer status to cancelled
    transfer.status = TransferStatus.CANCELLED
    await db.commit()
    
    logger.info(f"Transfer {transfer_id} cancelled for asset {asset_id}")
    return None


@router.post("/{asset_id}/share", response_model=Dict[str, ShareResponse], status_code=status.HTTP_201_CREATED)
async def share_asset_details(
    asset_id: UUID,
    share_data: ShareRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate shareable link for asset details"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Generate share link
    access_code = secrets.token_urlsafe(16)
    share_link = f"/assets/{asset_id}/shared?code={access_code}"
    
    expires_at = None
    if share_data.expires_in:
        expires_at = datetime.now(timezone.utc) + timedelta(days=share_data.expires_in)
    
    # Create share record
    share = AssetShare(
        asset_id=asset.id,
        share_link=share_link,
        access_code=access_code,
        email=share_data.email,
        expires_at=expires_at,
        permissions=share_data.permissions or ["view"]
    )
    
    db.add(share)
    await db.commit()
    
    logger.info(f"Share link created for asset {asset_id}: {share.id}")
    return {
        "data": ShareResponse(
            share_link=share_link,
            expires_at=expires_at,
            access_code=access_code
        )
    }


@router.post("/{asset_id}/reports", response_model=Dict[str, ReportResponse], status_code=status.HTTP_201_CREATED)
async def generate_asset_report(
    asset_id: UUID,
    report_data: ReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate a comprehensive report for an asset"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Create report record (actual report generation would be done asynchronously)
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)  # Reports expire in 30 days
    
    report = AssetReport(
        asset_id=asset.id,
        report_type=report_data.report_type,
        include_documents=report_data.include_documents,
        include_value_history=report_data.include_value_history,
        include_appraisals=report_data.include_appraisals,
        expires_at=expires_at
    )
    
    db.add(report)
    await db.commit()
    await db.refresh(report)
    
    # TODO: Generate actual report file asynchronously
    # For now, return the report record
    
    logger.info(f"Report generation requested for asset {asset_id}: {report.id}")
    return {"data": ReportResponse.model_validate(report)}


@router.get("/{asset_id}/reports/{report_id}", response_model=Dict[str, ReportResponse])
async def get_asset_report_status(
    asset_id: UUID,
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get status of a generated report"""
    account = await get_account(current_user=current_user, db=db)
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get report
    report_result = await db.execute(
        select(AssetReport).where(
            and_(AssetReport.id == report_id, AssetReport.asset_id == asset_id)
        )
    )
    report = report_result.scalar_one_or_none()
    if not report:
        raise NotFoundException("Report", str(report_id))
    
    return {"data": ReportResponse.model_validate(report)}


# ==================== ANALYTICS ====================

@router.get("/summary", response_model=Dict[str, AssetsSummaryResponse])
async def get_assets_summary(
    category_group: Optional[str] = Query(None, description="Filter by category group"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get summary statistics for all assets"""
    account = await get_account(current_user=current_user, db=db)
    
    # Get all assets
    query = select(Asset).where(Asset.account_id == account.id)
    if category_group:
        # Note: This would require category_group field in Asset model
        pass
    
    result = await db.execute(query)
    assets = result.scalars().all()
    
    if not assets:
        return {
            "data": AssetsSummaryResponse(
                total_assets=0,
                total_value=Decimal("0.00"),
                total_estimated_value=Decimal("0.00"),
                currency="USD",
                by_category=[],
                by_category_group=[],
                recently_added=0,
                pending_appraisals=0,
                pending_sales=0
            )
        }
    
    # Calculate summary
    total_value = sum([asset.current_value for asset in assets])
    total_estimated_value = total_value  # Assuming same for now
    
    # Get pending appraisals
    appraisals_result = await db.execute(
        select(func.count(AssetAppraisal.id)).join(Asset).where(
            and_(
                Asset.account_id == account.id,
                AssetAppraisal.status == AppraisalStatus.PENDING
            )
        )
    )
    pending_appraisals = appraisals_result.scalar() or 0
    
    # Get pending sales
    sales_result = await db.execute(
        select(func.count(AssetSaleRequest.id)).join(Asset).where(
            and_(
                Asset.account_id == account.id,
                AssetSaleRequest.status == SaleRequestStatus.PENDING
            )
        )
    )
    pending_sales = sales_result.scalar() or 0
    
    # Get recently added (last 30 days)
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    recent_result = await db.execute(
        select(func.count(Asset.id)).where(
            and_(
                Asset.account_id == account.id,
                Asset.created_at >= thirty_days_ago
            )
        )
    )
    recently_added = recent_result.scalar() or 0
    
    # Group by category (using asset_type for now)
    by_category = {}
    for asset in assets:
        category = asset.asset_type.value
        if category not in by_category:
            by_category[category] = {"count": 0, "value": Decimal("0.00")}
        by_category[category]["count"] += 1
        by_category[category]["value"] += asset.current_value
    
    category_list = [
        {"category": k, "count": v["count"], "total_value": v["value"]}
        for k, v in by_category.items()
    ]
    
    return {
        "data": AssetsSummaryResponse(
            total_assets=len(assets),
            total_value=total_value,
            total_estimated_value=total_estimated_value,
            currency=assets[0].currency if assets else "USD",
            by_category=category_list,
            by_category_group=[],  # Would need category_group implementation
            recently_added=recently_added,
            pending_appraisals=pending_appraisals,
            pending_sales=pending_sales
        )
    }


@router.get("/value-trends", response_model=ValueTrendsResponse)
async def get_asset_value_trends(
    period: Optional[str] = Query("30d", description="Time period (7d, 30d, 90d, 1y, all)"),
    category_group: Optional[str] = Query(None, description="Filter by category group"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get value trends across all assets"""
    account = await get_account(current_user=current_user, db=db)
    
    # Calculate date range based on period
    end_date = datetime.now(timezone.utc)
    if period == "7d":
        start_date = end_date - timedelta(days=7)
    elif period == "30d":
        start_date = end_date - timedelta(days=30)
    elif period == "90d":
        start_date = end_date - timedelta(days=90)
    elif period == "1y":
        start_date = end_date - timedelta(days=365)
    else:  # all
        start_date = None
    
    # Get all valuations for assets in this account
    query = select(AssetValuation).join(Asset).where(Asset.account_id == account.id)
    
    if start_date:
        query = query.where(AssetValuation.valuation_date >= start_date)
    
    query = query.order_by(asc(AssetValuation.valuation_date))
    
    result = await db.execute(query)
    valuations = result.scalars().all()
    
    # Group by date and calculate totals
    trends = {}
    for val in valuations:
        date_key = val.valuation_date.date()
        if date_key not in trends:
            trends[date_key] = {"total": Decimal("0.00"), "count": 0}
        trends[date_key]["total"] += val.value
        trends[date_key]["count"] += 1
    
    # Build response
    trend_items = []
    prev_value = None
    for date_key in sorted(trends.keys()):
        total_value = trends[date_key]["total"]
        change = total_value - prev_value if prev_value else Decimal("0.00")
        change_percent = (change / prev_value * 100) if prev_value and prev_value > 0 else Decimal("0.00")
        
        trend_items.append(ValueTrendItem(
            date=datetime.combine(date_key, datetime.min.time()),
            total_value=total_value,
            change=change,
            change_percent=change_percent
        ))
        
        prev_value = total_value
    
    return ValueTrendsResponse(data=trend_items)


# ==================== GENERAL FILE UPLOAD ====================

@router.post("/files/upload", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def upload_file_assets(
    file: UploadFile = File(...),
    file_type: str = Form(..., description="File type: photo or document"),
    asset_id: Optional[UUID] = Form(None, description="Asset ID if uploading for specific asset"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """General file upload endpoint (assets-specific)"""
    account = await get_account(current_user=current_user, db=db)
    
    # Validate file type
    if file_type not in ["photo", "document"]:
        raise BadRequestException("file_type must be 'photo' or 'document'")
    
    # Read file
    file_data = await file.read()
    file_size = len(file_data)
    
    if file_size > settings.MAX_UPLOAD_SIZE:
        raise BadRequestException(f"File size exceeds maximum allowed size")
    
    # Upload to Supabase
    folder = "assets" if asset_id else "general"
    file_path = f"{folder}/{account.id}/{file.filename}"
    
    try:
        SupabaseClient.upload_file(
            bucket="documents",
            file_path=file_path,
            file_data=file_data,
            content_type=file.content_type or "application/octet-stream"
        )
        url = SupabaseClient.get_file_url("documents", file_path)
        thumbnail_url = url if file_type == "photo" else None
    except Exception as e:
        logger.error(f"Failed to upload file: {e}")
        raise BadRequestException("Failed to upload file")
    
    # If asset_id provided, create asset photo/document record
    file_id = None
    if asset_id:
        asset_result = await db.execute(
            select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
        )
        asset = asset_result.scalar_one_or_none()
        if asset:
            if file_type == "photo":
                photo = AssetPhoto(
                    asset_id=asset.id,
                    file_name=file.filename,
                    file_path=file_path,
                    file_size=file_size,
                    mime_type=file.content_type,
                    url=url,
                    supabase_storage_path=file_path
                )
                db.add(photo)
                await db.commit()
                await db.refresh(photo)
                file_id = photo.id
            else:
                document = AssetDocument(
                    asset_id=asset.id,
                    name=file.filename,
                    file_name=file.filename,
                    file_path=file_path,
                    file_size=file_size,
                    mime_type=file.content_type,
                    url=url,
                    supabase_storage_path=file_path
                )
                db.add(document)
                await db.commit()
                await db.refresh(document)
                file_id = document.id
    
    return {
        "data": {
            "id": str(file_id) if file_id else None,
            "url": url,
            "thumbnail_url": thumbnail_url,
            "file_name": file.filename,
            "file_size": file_size,
            "file_type": file_type,
            "uploaded_at": datetime.now(timezone.utc).isoformat()
        }
    }

