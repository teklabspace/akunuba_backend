from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func as sql_func, desc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime, timedelta
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.asset import Asset, AssetType, AssetValuation, AssetOwnership
from app.schemas.asset import AssetCreate, AssetUpdate, AssetResponse
from app.schemas.common import PaginatedResponse
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from app.api.deps import get_account, get_user_subscription_plan
from app.core.features import get_limit, check_usage_limit
from sqlalchemy import func
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


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


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    asset_data: AssetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
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
    
    asset = Asset(
        account_id=account.id,
        asset_type=asset_data.asset_type,
        name=asset_data.name,
        symbol=asset_data.symbol,
        description=asset_data.description,
        current_value=asset_data.current_value,
        currency=asset_data.currency,
        meta_data=asset_data.metadata,
    )
    
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    
    # Create initial valuation
    valuation = AssetValuation(
        asset_id=asset.id,
        value=asset_data.current_value,
        currency=asset_data.currency,
        valuation_method="initial",
        valuation_date=datetime.utcnow(),
    )
    db.add(valuation)
    
    # Create ownership record
    ownership = AssetOwnership(
        asset_id=asset.id,
        account_id=account.id,
        ownership_percentage=Decimal("100.00"),
    )
    db.add(ownership)
    
    await db.commit()
    
    logger.info(f"Asset created: {asset.id} for account {account.id}")
    return asset


@router.get("", response_model=PaginatedResponse)
async def list_assets(
    asset_type: Optional[AssetType] = Query(None, description="Filter by asset type"),
    search: Optional[str] = Query(None, description="Search by name or symbol"),
    min_value: Optional[Decimal] = Query(None, description="Minimum asset value"),
    max_value: Optional[Decimal] = Query(None, description="Maximum asset value"),
    currency: Optional[str] = Query(None, description="Filter by currency"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List assets with pagination and filtering"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        return PaginatedResponse(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            pages=0
        )
    
    # Build query
    query = select(Asset).where(Asset.account_id == account.id)
    count_query = select(sql_func.count()).select_from(Asset).where(Asset.account_id == account.id)
    
    # Apply filters
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
        count_query = count_query.where(Asset.asset_type == asset_type)
    
    if search:
        search_filter = or_(
            Asset.name.ilike(f"%{search}%"),
            Asset.symbol.ilike(f"%{search}%")
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
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(desc(Asset.created_at)).offset(offset).limit(page_size)
    
    # Execute query
    result = await db.execute(query)
    assets = result.scalars().all()
    
    # Calculate pages
    pages = (total + page_size - 1) // page_size if total > 0 else 0
    
    return PaginatedResponse(
        items=[AssetResponse.model_validate(asset) for asset in assets],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages
    )


@router.get("/{asset_id}", response_model=AssetDetailResponse)
async def get_asset(
    asset_id: UUID,
    include_valuations: bool = Query(True, description="Include valuation history"),
    include_ownership: bool = Query(True, description="Include ownership details"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get asset details with optional valuations and ownership information"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Get asset with relationships
    query = select(Asset).where(
        and_(Asset.id == asset_id, Asset.account_id == account.id)
    )
    
    if include_valuations or include_ownership:
        query = query.options(selectinload(Asset.valuations), selectinload(Asset.ownerships))
    
    result = await db.execute(query)
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise NotFoundException("Asset", str(asset_id))
    
    # Get valuations if requested
    valuations = []
    if include_valuations and asset.valuations:
        valuations = [
            ValuationResponse.model_validate(v) 
            for v in sorted(asset.valuations, key=lambda x: x.valuation_date, reverse=True)
        ]
    
    # Get ownership details if requested
    ownerships = []
    total_ownership = Decimal("0.00")
    if include_ownership and asset.ownerships:
        ownerships = [OwnershipResponse.model_validate(o) for o in asset.ownerships]
        total_ownership = sum([o.ownership_percentage for o in asset.ownerships])
    
    asset_response = AssetResponse.model_validate(asset)
    return AssetDetailResponse(
        **asset_response.model_dump(),
        valuations=valuations,
        ownerships=ownerships,
        total_ownership_percentage=total_ownership
    )


@router.put("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: UUID,
    asset_data: AssetUpdate,
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
    
    # Update asset fields
    if asset_data.name is not None:
        asset.name = asset_data.name
    if asset_data.description is not None:
        asset.description = asset_data.description
    if asset_data.current_value is not None:
        # Create new valuation if value changed
        if asset.current_value != asset_data.current_value:
            valuation = AssetValuation(
                asset_id=asset.id,
                value=asset_data.current_value,
                currency=asset.currency,
                valuation_method="manual_update",
                valuation_date=datetime.utcnow(),
            )
            db.add(valuation)
        asset.current_value = asset_data.current_value
    if asset_data.metadata is not None:
        asset.meta_data = asset_data.metadata
    
    await db.commit()
    await db.refresh(asset)
    
    logger.info(f"Asset updated: {asset.id}")
    return asset


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


@router.post("/{asset_id}/valuations", status_code=status.HTTP_201_CREATED)
async def create_valuation(
    asset_id: UUID,
    value: Decimal,
    currency: str = "USD",
    valuation_method: Optional[str] = None,
    notes: Optional[str] = None,
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
        value=value,
        currency=currency,
        valuation_method=valuation_method or "manual",
        valuation_date=datetime.utcnow(),
        notes=notes,
    )
    
    # Update asset current value
    asset.current_value = value
    asset.currency = currency
    
    db.add(valuation)
    await db.commit()
    await db.refresh(valuation)
    
    logger.info(f"Valuation created for asset {asset_id}")
    return valuation


@router.get("/{asset_id}/valuations", response_model=List[ValuationResponse])
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
    
    return [ValuationResponse.model_validate(v) for v in valuations]


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

