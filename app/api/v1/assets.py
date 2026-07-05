from fastapi import APIRouter, Depends, HTTPException, status, Query, File, UploadFile, Form, Body
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func as sql_func, func, desc, asc, inspect as sqlalchemy_inspect
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.core.permissions import Role
from app.models.account import Account
from app.models.asset import (
    Asset, AssetType, AssetValuation, AssetOwnership, AssetCategory, AssetPhoto,
    AssetDocument, AssetAppraisal, AssetAIReview, AssetSaleRequest, AssetTransfer, AssetShare,
    AssetReport, CategoryGroup, AppraisalType, AppraisalStatus, AIReviewStatus, SaleRequestStatus,
    TransferStatus, TransferType, ReportType, AssetStatus, OwnershipType, Condition, ValuationType,
    AppraisalComment, AppraisalDocument, CommentType
)
from app.schemas.asset import AssetCreate, AssetUpdate, AssetResponse
from app.schemas.asset_extended import (
    CategoryResponse, CategoryGroupResponse, PhotoResponse, PhotoUploadResponse,
    DocumentResponse, DocumentListResponse, AppraisalRequest, AppraisalResponse,
    AppraisalListResponse, SaleRequestCreate, SaleRequestResponse, SaleRequestListResponse,
    TransferRequest, TransferResponse, ShareRequest, ShareResponse, ReportRequest,
    ReportResponse, ValueHistoryResponse, ValueHistoryItem, AssetsSummaryResponse,
    ValueTrendsResponse, ValueTrendItem, ValuationUpdate,
    AutomatedAppraisalResult, AIReviewResponse, AIUsageItem, AIUsageResponse
)
from app.schemas.common import PaginatedResponse
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from app.api.deps import get_account, get_user_subscription_plan
from app.core.features import get_limit, check_usage_limit
from app.services import ai_appraisal_service
from app.services import appraisal_thread
from app.utils.logger import logger
from app.integrations.supabase_client import SupabaseClient
from app.config import settings
from app.utils.upload_helpers import (
    resolve_content_type,
    storage_bucket_for_file_type,
    validate_image_content_type,
)
from uuid import UUID
from pydantic import BaseModel
import secrets

router = APIRouter()

# Category reference data is public (no auth/KYC): the marketplace browse
# experience filters by these same canonical values. Mounted without the KYC
# gate in app/main.py.
public_router = APIRouter()


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


async def generate_asset_code(db: AsyncSession) -> str:
    """Build the next globally-unique human-readable asset code (AK-01, AK-02, ...).

    Draws from the Postgres sequence `asset_code_seq` so concurrent creates never
    collide. Falls back to a count-based number if the sequence is missing (e.g.
    the migration has not run yet); the unique constraint still guards collisions.
    """
    try:
        result = await db.execute(select(func.nextval("asset_code_seq")))
        n = result.scalar()
    except Exception:
        result = await db.execute(select(func.count(Asset.id)))
        n = (result.scalar() or 0) + 1
    return f"AK-{int(n):02d}"


async def resolve_readable_asset(asset_id: UUID, current_user: User, db: AsyncSession) -> Asset:
    """Resolve an asset for a read-only operation, enforcing visibility rules.

    Investors may only read assets owned by their own account; admins may read
    any user's asset. Raises NotFoundException when the asset doesn't exist or
    isn't visible to the caller.
    """
    query = select(Asset).where(Asset.id == asset_id)
    if current_user.role != Role.ADMIN:
        account = await get_account(current_user=current_user, db=db)
        query = query.where(Asset.account_id == account.id)
    asset = (await db.execute(query)).scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    return asset


def serialize_asset_document(doc: AssetDocument) -> Dict[str, Any]:
    """Serialize an AssetDocument to the canonical document shape.

    Shared by GET /assets/{id}/documents and the embedded documents array on
    GET /admin/assets/{code} so both endpoints return identical fields.
    """
    doc_url = doc.url if doc.url else None
    if not doc_url or not doc_url.startswith(('http://', 'https://')):
        # If URL is relative or missing, resolve a public URL from Supabase.
        if getattr(doc, 'supabase_storage_path', None):
            try:
                doc_url = SupabaseClient.get_file_url("documents", doc.supabase_storage_path)
            except Exception as e:
                logger.warning(f"Failed to get public URL for document {doc.id}: {e}")
                doc_url = doc.url if doc.url else None

    return {
        "id": str(doc.id),
        "name": doc.name,
        "url": doc_url,  # Public download URL
        "file_name": doc.file_name,
        "document_type": doc.document_type,
        "file_size": doc.file_size,
        "type": doc.mime_type,  # MIME type
        "date": doc.date.isoformat() if doc.date else None,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


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
        "asset_code": asset.asset_code,
        "account_id": str(asset.account_id) if asset.account_id else None,
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
        
        # Check usage limit — admins are exempt
        if current_user.role.value != "admin":
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
                # Auto-create the category so category_id is always saved
                cg = category_group_enum
                if cg is None and asset_data.category_group:
                    # category_group_enum not resolved yet — do a quick parse
                    try:
                        cg = CategoryGroup(asset_data.category_group) if isinstance(asset_data.category_group, str) else asset_data.category_group
                    except ValueError:
                        cg = CategoryGroup.ASSETS
                if cg is None:
                    cg = CategoryGroup.ASSETS
                new_category = AssetCategory(
                    name=asset_data.category,
                    category_group=cg,
                    is_active=True,
                )
                db.add(new_category)
                await db.flush()  # get the id without full commit
                category_id = new_category.id
                category_group_enum = cg
                logger.info(f"Auto-created category: {asset_data.category} (ID: {category_id})")
        
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
        
        # Generate the human-readable, globally-unique code shown to users (AK-01, ...)
        asset_code = await generate_asset_code(db)

        # EnumValueType will automatically convert enum members to their values
        # So we can pass enum members directly - TypeDecorator handles the conversion
        asset = Asset(
            account_id=account.id,
            asset_code=asset_code,
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
        
        # Merge images field into photos (frontend may send either or both)
        all_photo_refs = list(dict.fromkeys(
            (asset_data.photos or []) + (asset_data.images or [])
        ))

        # Link photos if provided (using URLs or IDs as identifiers)
        if all_photo_refs:
            asset_data.photos = all_photo_refs

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

        # Reload asset with all relationships for full response
        result = await db.execute(
            select(Asset)
            .options(
                selectinload(Asset.category),
                selectinload(Asset.photos),
                selectinload(Asset.documents),
            )
            .where(Asset.id == asset.id)
        )
        asset = result.scalar_one()

        logger.info(f"Asset created: {asset.id} for account {account.id}")

        # Every active ("Active Investment") asset is public in the marketplace.
        from app.services.asset_listing_service import ensure_listing_for_active_asset
        await ensure_listing_for_active_asset(db, asset)

        return {"data": build_asset_response(asset)}
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
    """List assets with pagination and filtering.

    Investors only ever see their own assets. Admins see every asset across all
    users and can search by the human-readable asset code (e.g. AK-01).
    """
    try:
        is_admin = current_user.role == Role.ADMIN

        # Use limit if provided, otherwise page_size
        items_per_page = limit or page_size

        # Build query with relationships
        query = select(Asset).options(
            selectinload(Asset.category),
            selectinload(Asset.photos),
            selectinload(Asset.documents)
        )
        count_query = select(sql_func.count()).select_from(Asset)

        if not is_admin:
            # Scope to the caller's own account; no account => no assets.
            account_result = await db.execute(
                select(Account).where(Account.user_id == current_user.id)
            )
            account = account_result.scalar_one_or_none()

            if not account:
                return {
                    "data": [],
                    "pagination": {
                        "page": page,
                        "limit": items_per_page,
                        "total": 0,
                        "total_pages": 0
                    }
                }

            query = query.where(Asset.account_id == account.id)
            count_query = count_query.where(Asset.account_id == account.id)

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
                Asset.description.ilike(f"%{search}%"),
                Asset.asset_code.ilike(f"%{search}%")
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
                    "asset_code": asset.asset_code,
                    "account_id": str(asset.account_id) if asset.account_id else None,
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


# ==================== SUMMARY (Must be before /{asset_id} route) ====================

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


@router.get("/{asset_id}", response_model=Dict[str, Any])
async def get_asset(
    asset_id: UUID,
    include_valuations: bool = Query(True, description="Include valuation history"),
    include_ownership: bool = Query(True, description="Include ownership details"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get asset details with all frontend-required fields.

    Investors can only fetch their own assets; admins can fetch any asset.
    """
    is_admin = current_user.role == Role.ADMIN

    # Get asset with all relationships
    query = select(Asset).where(Asset.id == asset_id).options(
        selectinload(Asset.category),
        selectinload(Asset.photos),
        selectinload(Asset.documents),
        selectinload(Asset.valuations),
        selectinload(Asset.ownerships),
        selectinload(Asset.appraisals)
    )

    if not is_admin:
        account_result = await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )
        account = account_result.scalar_one_or_none()

        if not account:
            raise NotFoundException("Account", str(current_user.id))

        query = query.where(Asset.account_id == account.id)
    
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
        # valuation_date can legitimately be NULL on legacy rows; sort those
        # last and skip them in the serialized history rather than 500.
        _epoch = datetime.min.replace(tzinfo=timezone.utc)
        for val in sorted(asset.valuations, key=lambda x: x.valuation_date or _epoch):
            if val.valuation_date is None:
                continue
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
    
    # If the asset is (still or newly) active, make sure it's on the marketplace.
    from app.services.asset_listing_service import ensure_listing_for_active_asset
    await ensure_listing_for_active_asset(db, asset)

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

@public_router.get("/categories", response_model=Dict[str, Any])
async def get_categories(
    db: AsyncSession = Depends(get_db)
):
    """Get all available asset categories (public, no auth).

    ``data`` is grouped by category_group (existing consumers); ``names`` is the
    flat canonical list — the same values accepted by asset creation and by the
    marketplace ``category`` filter.
    """
    from collections import defaultdict
    result = await db.execute(
        select(AssetCategory)
        .where(AssetCategory.is_active == True)
        .order_by(AssetCategory.category_group, AssetCategory.name)
    )
    categories = result.scalars().all()

    grouped: dict = defaultdict(list)
    for cat in categories:
        grouped[cat.category_group.value].append(CategoryResponse.model_validate(cat))

    return {
        "data": {group: cats for group, cats in grouped.items()},
        "names": [cat.name for cat in categories],
        "total": len(categories),
    }


@public_router.get("/category-groups", response_model=Dict[str, List[str]])
async def get_category_groups(
    db: AsyncSession = Depends(get_db)
):
    """Get all category groups (public, no auth)"""
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
    
    # Validate and resolve image content type (JPG, PNG, GIF, WEBP only)
    try:
        content_type = validate_image_content_type(file.filename or "upload", file.content_type)
    except ValueError as e:
        raise BadRequestException(str(e))
    
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
            content_type=content_type,
        )
        url = SupabaseClient.get_file_url("images", file_path)
    except Exception as e:
        logger.error(f"Failed to upload photo: {e}")
        raise BadRequestException(f"Failed to upload photo: {e}")
    
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
    # Admins may read any user's asset; investors are scoped to their own.
    asset = await resolve_readable_asset(asset_id, current_user, db)

    # Get documents
    result = await db.execute(
        select(AssetDocument).where(AssetDocument.asset_id == asset_id).order_by(desc(AssetDocument.created_at))
    )
    documents = result.scalars().all()

    documents_data = [serialize_asset_document(doc) for doc in documents]

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
    # Admins may read any user's asset; investors are scoped to their own.
    asset = await resolve_readable_asset(asset_id, current_user, db)

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
        if val.valuation_date is None:
            continue  # legacy rows without a date can't be placed on the timeline
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

def _current_month_period() -> str:
    """Current calendar month as 'YYYY-MM' (UTC)."""
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def _current_month_start() -> datetime:
    """First instant of the current calendar month (UTC)."""
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


async def _count_ai_appraisals_this_month(db: AsyncSession, account_id) -> int:
    """Number of automated (AI) appraisals this account has run this month."""
    result = await db.execute(
        select(func.count(AssetAppraisal.id))
        .join(Asset, AssetAppraisal.asset_id == Asset.id)
        .where(
            Asset.account_id == account_id,
            AssetAppraisal.appraisal_type == AppraisalType.API,
            AssetAppraisal.requested_at >= _current_month_start(),
        )
    )
    return result.scalar() or 0


async def _count_ai_reviews_this_month(db: AsyncSession, account_id) -> int:
    """Number of AI asset reviews this account has run this month."""
    result = await db.execute(
        select(func.count(AssetAIReview.id))
        .join(Asset, AssetAIReview.asset_id == Asset.id)
        .where(
            Asset.account_id == account_id,
            AssetAIReview.created_at >= _current_month_start(),
        )
    )
    return result.scalar() or 0


def _build_asset_context(asset: Asset) -> Dict[str, Any]:
    """Flatten an asset's valuation-relevant fields for an AI prompt."""
    return {
        "name": asset.name,
        "category_name": asset.category.name if asset.category else None,
        "asset_type": asset.asset_type.value if asset.asset_type else None,
        "category_group": asset.category_group.value if asset.category_group else None,
        "description": asset.description,
        "location": asset.location,
        "current_value": float(asset.current_value) if asset.current_value is not None else None,
        "estimated_value": float(asset.estimated_value) if asset.estimated_value is not None else None,
        "currency": asset.currency,
        "condition": asset.condition.value if asset.condition else None,
        "purchase_price": float(asset.purchase_price) if asset.purchase_price is not None else None,
        "acquisition_date": asset.acquisition_date.isoformat() if asset.acquisition_date else None,
        "specifications": asset.specifications,
    }


@router.post("/{asset_id}/appraisals", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def request_asset_appraisal(
    asset_id: UUID,
    appraisal_data: AppraisalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Request an appraisal for an asset.

    - appraisal_type == "API" (Automated Appraisal): an instant AI-generated value
      estimate. Completes immediately and returns an `ai_result` with a disclaimer.
    - any other type (e.g. "Concierge"): a human appraisal request, created as
      PENDING for the concierge workflow (unchanged behaviour).
    """
    account = await get_account(current_user=current_user, db=db)

    # Verify asset belongs to account, eagerly loading category for type-specific AI prompts
    asset_result = await db.execute(
        select(Asset)
        .options(selectinload(Asset.category))
        .where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))

    # ---- Automated (AI) appraisal: instant estimate, no human in the loop ----
    if appraisal_data.appraisal_type == AppraisalType.API:
        # Enforce per-plan monthly AI usage limit (admins exempt)
        if current_user.role.value != "admin":
            plan = await get_user_subscription_plan(account=account, db=db)
            used = await _count_ai_appraisals_this_month(db, account.id)
            if not check_usage_limit(plan, "ai_appraisals_per_month", used):
                limit = get_limit(plan, "ai_appraisals_per_month")
                raise ForbiddenException(
                    f"Automated appraisal limit reached ({limit}/month for your plan). Upgrade for more."
                )

        now = datetime.now(timezone.utc)
        appraisal_status = AppraisalStatus.APPRAISAL_FAILED
        ai_result = None

        try:
            ai_result = await ai_appraisal_service.generate_automated_appraisal(
                _build_asset_context(asset)
            )

            # Determine status based on AI analysis (Option A: always return estimate)
            if ai_result.get("professional_appraisal_needed"):
                appraisal_status = AppraisalStatus.PROFESSIONAL_APPRAISAL_RECOMMENDED
            elif ai_result.get("missing_information"):
                appraisal_status = AppraisalStatus.NEEDS_MORE_INFORMATION
            else:
                appraisal_status = AppraisalStatus.AI_APPRAISED

        except Exception as exc:
            logger.error(f"AI appraisal failed for asset {asset_id}: {exc}")
            appraisal = AssetAppraisal(
                asset_id=asset.id,
                appraisal_type=AppraisalType.API,
                status=AppraisalStatus.APPRAISAL_FAILED,
                notes=str(exc),
                completed_at=now,
            )
            db.add(appraisal)
            await db.commit()
            await db.refresh(appraisal)
            raise

        estimated_value = Decimal(str(ai_result["estimated_value"]))

        # Build serialisable ai_data dict (exclude non-JSON-safe keys already stored elsewhere)
        ai_data_store = {
            "confidence": ai_result.get("confidence"),
            "appraisal_summary": ai_result.get("appraisal_summary"),
            "key_value_drivers": ai_result.get("key_value_drivers", []),
            "risk_factors": ai_result.get("risk_factors", []),
            "missing_information": ai_result.get("missing_information", []),
            "recommended_documents": ai_result.get("recommended_documents", []),
            "suggested_next_step": ai_result.get("suggested_next_step"),
            "professional_appraisal_needed": ai_result.get("professional_appraisal_needed", False),
            "value_range_low": float(ai_result.get("value_range_low", 0)),
            "value_range_high": float(ai_result.get("value_range_high", 0)),
            "currency": ai_result.get("currency"),
            "model": ai_result.get("model"),
            "disclaimer": ai_result.get("disclaimer"),
        }

        appraisal = AssetAppraisal(
            asset_id=asset.id,
            appraisal_type=AppraisalType.API,
            status=appraisal_status,
            notes=ai_result.get("appraisal_summary"),
            estimated_value=estimated_value,
            completed_at=now,
            ai_data=ai_data_store,
        )
        db.add(appraisal)

        # Record valuation history and update asset estimate
        valuation = AssetValuation(
            asset_id=asset.id,
            value=estimated_value,
            currency=ai_result.get("currency") or asset.currency,
            valuation_method=ValuationType.AUTOMATED.value,
            valuation_date=now,
            notes=ai_result.get("appraisal_summary"),
        )
        db.add(valuation)

        asset.estimated_value = estimated_value
        asset.valuation_type = ValuationType.AUTOMATED
        asset.last_appraisal_date = now

        await db.commit()
        await db.refresh(appraisal)

        logger.info(
            f"AI appraisal generated for asset {asset_id}: {appraisal.id} "
            f"status={appraisal_status.value} confidence={ai_result.get('confidence')}"
        )
        return {
            "data": AppraisalResponse.model_validate(appraisal),
            "ai_result": AutomatedAppraisalResult(**ai_result),
        }

    # ---- Concierge / other types: human appraisal request (PENDING) ----
    # Enforce one OPEN human appraisal per asset. Run before any write so a
    # blocked request never leaves a partial record. AI ("API") is exempt
    # (handled in the branch above and never reaches here).
    OPEN_HUMAN_STATUSES = [
        AppraisalStatus.PENDING,
        AppraisalStatus.IN_PROGRESS,
        AppraisalStatus.NEEDS_MORE_INFORMATION,
        AppraisalStatus.PROFESSIONAL_APPRAISAL_RECOMMENDED,
    ]
    existing_open = (await db.execute(
        select(AssetAppraisal)
        .where(and_(
            AssetAppraisal.asset_id == asset.id,
            AssetAppraisal.appraisal_type != AppraisalType.API,
            AssetAppraisal.status.in_(OPEN_HUMAN_STATUSES),
        ))
        .order_by(desc(AssetAppraisal.requested_at))
        .limit(1)
    )).scalar_one_or_none()
    if existing_open is not None:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "An appraisal is already in progress for this asset.",
                "existing_appraisal": {
                    "id": str(existing_open.id),
                    "appraisal_type": existing_open.appraisal_type.value if existing_open.appraisal_type else None,
                    "status": existing_open.status.value if existing_open.status else None,
                },
            },
        )

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

    # Notify staff (admins/advisors) that an investor requested a human appraisal.
    from app.services.appraisal_notifications import dispatch_appraisal_created
    await dispatch_appraisal_created(db, appraisal, asset, current_user)

    logger.info(f"Appraisal requested for asset {asset_id}: {appraisal.id}")
    return {"data": AppraisalResponse.model_validate(appraisal)}


@router.get("/{asset_id}/appraisals", response_model=AppraisalListResponse)
async def get_asset_appraisals(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all appraisals for an asset"""
    # Admins may read any user's asset; investors are scoped to their own.
    asset = await resolve_readable_asset(asset_id, current_user, db)

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


# ==================== APPRAISAL THREAD (investor-facing) ====================
# Client-visible comments & documents for an appraisal the investor owns.
# Visibility is enforced here: only is_internal=False comments and
# is_client_visible=True documents are ever returned, and investor posts are
# always non-internal. Staff-side equivalents live in concierge.py.


class InvestorCommentCreate(BaseModel):
    body: str


async def _owned_appraisal_or_404(asset_id: UUID, appraisal_id: UUID, current_user: User, db: AsyncSession) -> AssetAppraisal:
    """Verify the appraisal belongs to an asset owned by the current user."""
    account = await get_account(current_user=current_user, db=db)
    asset = (await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )).scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    appraisal = (await db.execute(
        select(AssetAppraisal).where(
            and_(AssetAppraisal.id == appraisal_id, AssetAppraisal.asset_id == asset_id)
        )
    )).scalar_one_or_none()
    if not appraisal:
        raise NotFoundException("Appraisal", str(appraisal_id))
    return appraisal


@router.get("/{asset_id}/appraisals/{appraisal_id}/comments", response_model=Dict[str, Any])
async def get_my_appraisal_comments(
    asset_id: UUID,
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Owner: list client-visible comments on your appraisal (no internal notes)."""
    await _owned_appraisal_or_404(asset_id, appraisal_id, current_user, db)

    comments = (await db.execute(
        select(AppraisalComment)
        .where(and_(
            AppraisalComment.appraisal_id == appraisal_id,
            AppraisalComment.is_internal.is_(False),
        ))
        .order_by(AppraisalComment.created_at)
    )).scalars().all()

    authors = await appraisal_thread.author_map(db, comments)
    return {
        "data": [
            appraisal_thread.serialize_comment(c, authors.get(c.author_user_id), for_investor=True)
            for c in comments
        ],
        "count": len(comments),
    }


@router.post("/{asset_id}/appraisals/{appraisal_id}/comments", response_model=Dict[str, Any])
async def post_my_appraisal_comment(
    asset_id: UUID,
    appraisal_id: UUID,
    comment_data: InvestorCommentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Owner: post a message on your appraisal (always client-visible)."""
    appraisal = await _owned_appraisal_or_404(asset_id, appraisal_id, current_user, db)

    comment = AppraisalComment(
        appraisal_id=appraisal_id,
        author_user_id=current_user.id,
        author_role=current_user.role.value,
        body=comment_data.body,
        comment_type=CommentType.MESSAGE.value,
        is_internal=False,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    # Notify staff (admins/advisors) of the investor's message.
    asset = (await db.execute(select(Asset).where(Asset.id == asset_id))).scalar_one_or_none()
    if asset is not None:
        from app.services.appraisal_notifications import dispatch_appraisal_message
        await dispatch_appraisal_message(db, appraisal, asset, comment, current_user)

    logger.info(f"Investor comment added to appraisal {appraisal_id}")
    return {"data": appraisal_thread.serialize_comment(comment, current_user, for_investor=True)}


@router.get("/{asset_id}/appraisals/{appraisal_id}/documents", response_model=Dict[str, Any])
async def get_my_appraisal_documents(
    asset_id: UUID,
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Owner: list client-visible documents on your appraisal."""
    await _owned_appraisal_or_404(asset_id, appraisal_id, current_user, db)

    documents = (await db.execute(
        select(AppraisalDocument)
        .where(and_(
            AppraisalDocument.appraisal_id == appraisal_id,
            AppraisalDocument.is_client_visible.is_(True),
        ))
        .order_by(desc(AppraisalDocument.created_at))
    )).scalars().all()

    authors = await appraisal_thread.author_map(db, documents)
    return {
        "data": [
            appraisal_thread.serialize_document(d, authors.get(d.uploaded_by_user_id), for_investor=True)
            for d in documents
        ],
        "count": len(documents),
    }


@router.post("/{asset_id}/appraisals/{appraisal_id}/documents", response_model=Dict[str, Any])
async def upload_my_appraisal_document(
    asset_id: UUID,
    appraisal_id: UUID,
    files: List[UploadFile] = File(...),
    fulfills_comment_id: Optional[UUID] = Query(None, description="Optional document_request comment id this upload fulfills"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Owner: upload one or more documents to your appraisal (always client-visible).

    Pass fulfills_comment_id to satisfy a staff document request.
    """
    await _owned_appraisal_or_404(asset_id, appraisal_id, current_user, db)

    # If fulfilling a request, validate it is a document_request on this appraisal
    if fulfills_comment_id is not None:
        req = (await db.execute(
            select(AppraisalComment).where(and_(
                AppraisalComment.id == fulfills_comment_id,
                AppraisalComment.appraisal_id == appraisal_id,
                AppraisalComment.comment_type == CommentType.DOCUMENT_REQUEST.value,
            ))
        )).scalar_one_or_none()
        if not req:
            raise BadRequestException("fulfills_comment_id is not a document request on this appraisal")

    created = []
    rejected = []
    for file in files:
        try:
            doc = await appraisal_thread.create_appraisal_document(
                db, appraisal_id, file,
                user_id=current_user.id,
                role=current_user.role.value,
                is_client_visible=True,
                fulfills_comment_id=fulfills_comment_id,
                asset_id=asset_id,
            )
            created.append(doc)
        except appraisal_thread.DocumentRejected as e:
            rejected.append({"file_name": e.file_name, "reason": e.reason})

    if not created and rejected:
        raise BadRequestException(
            "No documents were saved: "
            + "; ".join(f"{r['file_name']} ({r['reason']})" for r in rejected)
        )

    await db.commit()
    for doc in created:
        await db.refresh(doc)

    logger.info(f"Investor uploaded {len(created)} document(s) to appraisal {appraisal_id}")
    return {
        "data": [appraisal_thread.serialize_document(d, current_user, for_investor=True) for d in created],
        "count": len(created),
        "rejected": rejected,
    }


@router.get("/{asset_id}/appraisals/{appraisal_id}/document-requests", response_model=Dict[str, Any])
async def get_my_appraisal_document_requests(
    asset_id: UUID,
    appraisal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Owner: list document requests on your appraisal with fulfillment state."""
    await _owned_appraisal_or_404(asset_id, appraisal_id, current_user, db)

    comments = (await db.execute(
        select(AppraisalComment)
        .where(and_(
            AppraisalComment.appraisal_id == appraisal_id,
            AppraisalComment.is_internal.is_(False),
        ))
        .order_by(AppraisalComment.created_at)
    )).scalars().all()
    documents = (await db.execute(
        select(AppraisalDocument).where(and_(
            AppraisalDocument.appraisal_id == appraisal_id,
            AppraisalDocument.is_client_visible.is_(True),
        ))
    )).scalars().all()

    requests = appraisal_thread.build_document_requests(comments, documents)
    return {"data": requests, "count": len(requests)}


# ==================== AI ASSET REVIEW ====================

@router.post("/{asset_id}/ai-review", response_model=Dict[str, AIReviewResponse], status_code=status.HTTP_201_CREATED)
async def run_ai_asset_review(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Run an AI review of an asset and its supporting documents.

    Returns an advisory accept/reject decision (approved / rejected / needs_review).
    The decision is recorded on the asset but is advisory only — it does not hide
    or block the asset by itself.
    """
    account = await get_account(current_user=current_user, db=db)

    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))

    # Enforce per-plan monthly AI usage limit (admins exempt)
    if current_user.role.value != "admin":
        plan = await get_user_subscription_plan(account=account, db=db)
        used = await _count_ai_reviews_this_month(db, account.id)
        if not check_usage_limit(plan, "ai_reviews_per_month", used):
            limit = get_limit(plan, "ai_reviews_per_month")
            raise ForbiddenException(
                f"AI review limit reached ({limit}/month for your plan). Upgrade for more."
            )

    # Gather supporting documents for context
    docs_result = await db.execute(
        select(AssetDocument).where(AssetDocument.asset_id == asset_id)
    )
    documents = [
        {"name": d.name, "document_type": d.document_type, "file_name": d.file_name}
        for d in docs_result.scalars().all()
    ]

    ai_result = await ai_appraisal_service.review_asset(_build_asset_context(asset), documents)

    decision = AIReviewStatus(ai_result["decision"])
    review = AssetAIReview(
        asset_id=asset.id,
        decision=decision,
        reason=ai_result.get("reason"),
        flags=ai_result.get("flags") or [],
        model=ai_result.get("model"),
    )
    db.add(review)

    # Update the asset's current advisory verdict
    asset.ai_review_status = decision
    asset.ai_reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(review)

    logger.info(f"AI review for asset {asset_id}: {decision.value} ({review.id})")
    return {"data": AIReviewResponse.model_validate(review)}


@router.get("/{asset_id}/ai-review", response_model=Dict[str, Optional[AIReviewResponse]])
async def get_latest_ai_review(
    asset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the latest AI review for an asset (null if none has been run)."""
    # Admins may read any user's asset; investors are scoped to their own.
    asset = await resolve_readable_asset(asset_id, current_user, db)

    review_result = await db.execute(
        select(AssetAIReview)
        .where(AssetAIReview.asset_id == asset_id)
        .order_by(desc(AssetAIReview.created_at))
        .limit(1)
    )
    review = review_result.scalar_one_or_none()
    return {"data": AIReviewResponse.model_validate(review) if review else None}


@router.get("/ai/usage", response_model=AIUsageResponse)
async def get_ai_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Show the caller's AI usage and remaining quota for the current month."""
    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)

    appraisals_used = await _count_ai_appraisals_this_month(db, account.id)
    reviews_used = await _count_ai_reviews_this_month(db, account.id)

    appraisals_limit = get_limit(plan, "ai_appraisals_per_month")
    reviews_limit = get_limit(plan, "ai_reviews_per_month")

    def _remaining(limit: Optional[int], used: int) -> Optional[int]:
        if limit is None:
            return None  # unlimited
        return max(0, limit - used)

    return AIUsageResponse(
        plan=plan.value,
        period=_current_month_period(),
        ai_appraisals=AIUsageItem(
            limit=appraisals_limit, used=appraisals_used, remaining=_remaining(appraisals_limit, appraisals_used)
        ),
        ai_reviews=AIUsageItem(
            limit=reviews_limit, used=reviews_used, remaining=_remaining(reviews_limit, reviews_used)
        ),
    )


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

    try:
        db.add(sale_request)
        await db.commit()
        await db.refresh(sale_request)
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create sale request for asset {asset_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create sale request"
        )

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
    
    # Generate share link as an absolute, reachable URL (relative paths can't be
    # opened directly from the clipboard). Points to the frontend share page,
    # which resolves the data via GET /api/v1/assets/{asset_id}/shared.
    access_code = secrets.token_urlsafe(16)
    base_url = settings.FRONTEND_BASE_URL.rstrip("/")
    share_link = f"{base_url}/assets/{asset_id}/shared?code={access_code}"

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


@router.get("/{asset_id}/shared", response_model=Dict[str, Any])
async def get_shared_asset(
    asset_id: UUID,
    code: str = Query(..., description="Share access code from the share link"),
    db: AsyncSession = Depends(get_db)
):
    """Resolve a time-limited share link and return the shared asset details.

    Public endpoint (no auth) — access is gated by the per-share access code.
    """
    share_result = await db.execute(
        select(AssetShare).where(
            and_(
                AssetShare.asset_id == asset_id,
                AssetShare.access_code == code,
                AssetShare.is_active == True
            )
        )
    )
    share = share_result.scalar_one_or_none()
    if not share:
        raise NotFoundException("Shared asset", str(asset_id))

    # Enforce expiry
    if share.expires_at is not None and share.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This share link has expired")

    asset_result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise NotFoundException("Asset", str(asset_id))

    return {
        "data": {
            "asset": AssetResponse.model_validate(asset),
            "permissions": share.permissions or ["view"],
            "expires_at": share.expires_at,
        }
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
    
    import uuid

    file_extension = file.filename.split(".")[-1] if "." in file.filename else ""
    base_name = file.filename.rsplit(".", 1)[0] if "." in file.filename else file.filename
    base_name = "".join(c for c in base_name if c.isalnum() or c in (" ", "-", "_")).strip()
    base_name = base_name.replace(" ", "_")[:50]
    unique_id = str(uuid.uuid4())[:8]
    unique_filename = (
        f"{base_name}_{unique_id}.{file_extension}" if file_extension else f"{base_name}_{unique_id}"
    )

    bucket_name = storage_bucket_for_file_type(file_type)
    folder = "assets" if asset_id else "general"
    file_path = f"{folder}/{account.id}/{unique_filename}"

    try:
        if file_type == "photo":
            content_type = validate_image_content_type(file.filename or unique_filename, file.content_type)
        else:
            content_type = resolve_content_type(file.filename or unique_filename, file.content_type)
    except ValueError as e:
        raise BadRequestException(str(e))

    try:
        SupabaseClient.upload_file(
            bucket=bucket_name,
            file_path=file_path,
            file_data=file_data,
            content_type=content_type,
        )
        url = SupabaseClient.get_file_url(bucket_name, file_path)
        thumbnail_url = url if file_type == "photo" else None
    except Exception as e:
        logger.error(f"Failed to upload file: {e}")
        raise BadRequestException(f"Failed to upload file: {e}")
    
    # Always create a DB record so the file always gets an ID.
    # asset_id is nullable — record is "floating" until linked to an asset.
    linked_asset_id = None
    if asset_id:
        asset_result = await db.execute(
            select(Asset).where(and_(Asset.id == asset_id, Asset.account_id == account.id))
        )
        found_asset = asset_result.scalar_one_or_none()
        if found_asset:
            linked_asset_id = found_asset.id

    file_id = None
    if file_type == "photo":
        photo = AssetPhoto(
            asset_id=linked_asset_id,
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
            asset_id=linked_asset_id,
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

