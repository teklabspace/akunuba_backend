from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, case
from sqlalchemy.orm import aliased, selectinload
from typing import List, Optional, Dict, Any, Literal
from decimal import Decimal
from datetime import datetime, timedelta, timezone as dt_timezone
from uuid import UUID
from app.database import get_db
from app.api.deps import get_current_user, require_kyc_verified
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.security import decode_access_token
from app.models.user import User
from app.models.account import Account, AccountType
from app.models.asset import Asset, AssetCategory, CategoryGroup, AssetDocument, AssetValuation
from app.models.marketplace import (
    MarketplaceListing, Offer, EscrowTransaction, WatchlistItem,
    ListingStatus, OfferStatus, EscrowStatus
)
from app.core.exceptions import NotFoundException, BadRequestException, UnauthorizedException, ForbiddenException
from app.core.permissions import Role, Permission, has_permission
from app.utils.logger import logger
from app.utils.helpers import calculate_listing_fee, calculate_commission, generate_reference_id
from app.integrations.stripe_client import StripeClient
from pydantic import BaseModel

security = HTTPBearer(auto_error=False)


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Get current user if authenticated, otherwise return None"""
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        payload = decode_access_token(token)
        if payload is None:
            return None
        
        user_id = payload.get("sub")
        if user_id is None:
            return None
        
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if user and user.is_active:
            return user
    except Exception:
        pass
    
    return None

router = APIRouter()

# Browse endpoints live on a separate router mounted WITHOUT the KYC gate:
# anyone (guest, unverified investor) may view public listings — auth/KYC is
# only required to transact (create listings, offers, escrow, watchlist, ...).
public_router = APIRouter()


class ListingOverview(BaseModel):
    summary: Optional[str] = None
    investment_rationale: List[str] = []
    asset_security: Optional[str] = None
    investment_objectives: List[str] = []


class ListingFAQ(BaseModel):
    question: str
    answer: str


class ListingDetailFields(BaseModel):
    """Seller-provided marketing content for the listing detail page.
    Stored in MarketplaceListing.meta_data (JSONB) — no dedicated columns."""
    expected_return: Optional[str] = None   # e.g. "7.2%"
    duration: Optional[str] = None          # e.g. "24 months"
    risk_level: Optional[Literal["low", "medium", "high"]] = None
    slots_total: Optional[int] = None
    slots_filled: Optional[int] = None
    overview: Optional[ListingOverview] = None
    faqs: Optional[List[ListingFAQ]] = None
    # AssetDocument ids (of the listing's asset) the seller exposes to buyers
    # on the public Documents tab. Anything not listed here stays private.
    document_ids: Optional[List[UUID]] = None


# meta_data keys used by the detail page
_DETAILS_KEY = "details"
_PUBLIC_DOCS_KEY = "public_document_ids"

_DETAIL_FIELD_NAMES = (
    "expected_return", "duration", "risk_level",
    "slots_total", "slots_filled", "overview", "faqs",
)


class ListingCreate(ListingDetailFields):
    asset_id: UUID
    title: str
    description: Optional[str] = None
    asking_price: Decimal
    currency: str = "USD"


class ListingResponse(BaseModel):
    id: UUID
    asset_id: Optional[UUID] = None
    title: str
    asking_price: Decimal
    currency: str
    status: str
    # Canonical asset category name (same values as GET /assets/categories).
    category: Optional[str] = None
    # Main category group of the asset's category (Assets, Portfolio, ...).
    category_group: Optional[str] = None
    listing_fee: Optional[Decimal] = None
    rejection_reason: Optional[str] = None
    # Primary asset photo: thumbnail_url for cards, image_url for detail pages.
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


def _primary_photo(photos):
    """The listing's display photo. Asset.photos is ordered is_primary-first,
    so the first row is the primary photo when one exists."""
    return photos[0] if photos else None


def _listing_with_category(listing: "MarketplaceListing") -> ListingResponse:
    """Serialize a listing including its asset's canonical category name,
    category group, and primary photo URLs.

    Callers must eager-load listing.asset, asset.category and asset.photos."""
    resp = ListingResponse.model_validate(listing)
    asset = listing.asset
    if asset is None:
        return resp
    if asset.category is not None:
        resp.category = asset.category.name
        group = asset.category.category_group
        resp.category_group = group.value if hasattr(group, "value") else group
    photo = _primary_photo(asset.photos)
    if photo is not None:
        resp.image_url = photo.url
        resp.thumbnail_url = photo.thumbnail_url or photo.url
    return resp


_LISTING_ASSET_LOAD = selectinload(MarketplaceListing.asset).options(
    selectinload(Asset.category),
    selectinload(Asset.photos),
)


class ListingDetailResponse(ListingResponse):
    """Full payload for the listing detail page. Nullable fields are hidden
    by the frontend when null."""
    description: Optional[str] = None
    seller_name: Optional[str] = None
    seller_id: Optional[UUID] = None      # listing owner's USER id (standardized)
    is_owner: bool = False                # computed for the authenticated caller
    fee_paid: bool = False
    expected_return: Optional[str] = None
    duration: Optional[str] = None
    risk_level: Optional[str] = None
    slots_total: Optional[int] = None
    slots_filled: Optional[int] = None
    overview: Optional[ListingOverview] = None
    faqs: Optional[List[ListingFAQ]] = None


def _listing_detail_response(listing: MarketplaceListing, is_owner: bool) -> ListingDetailResponse:
    """Detail-page serialization. Callers must eager-load listing.asset
    (category+photos) and listing.account.user."""
    meta = listing.meta_data or {}
    details = meta.get(_DETAILS_KEY) or {}
    seller_user = listing.account.user if listing.account else None
    return ListingDetailResponse(
        **_listing_with_category(listing).model_dump(),
        description=listing.description,
        seller_name=_full_name(seller_user) if seller_user else None,
        seller_id=seller_user.id if seller_user else None,
        is_owner=is_owner,
        fee_paid=bool(listing.listing_fee_paid),
        expected_return=details.get("expected_return"),
        duration=details.get("duration"),
        risk_level=details.get("risk_level"),
        slots_total=details.get("slots_total"),
        slots_filled=details.get("slots_filled"),
        overview=details.get("overview"),
        faqs=details.get("faqs"),
    )


async def _apply_listing_details(listing: MarketplaceListing, data: ListingDetailFields, db: AsyncSession) -> None:
    """Merge seller-provided detail fields into listing.meta_data.

    Only fields explicitly present in the request change (send null/[] to
    clear one). document_ids are validated to belong to the listing's own
    asset — this is the seller's explicit opt-in that makes those documents
    publicly visible on the Documents tab."""
    provided = data.model_dump(exclude_unset=True, mode="json")
    meta = dict(listing.meta_data or {})
    details = dict(meta.get(_DETAILS_KEY) or {})

    for field in _DETAIL_FIELD_NAMES:
        if field in provided:
            if provided[field] is None:
                details.pop(field, None)
            else:
                details[field] = provided[field]
    meta[_DETAILS_KEY] = details

    if "document_ids" in provided:
        doc_ids = data.document_ids or []
        if doc_ids:
            valid_rows = await db.execute(
                select(AssetDocument.id).where(
                    AssetDocument.id.in_(doc_ids),
                    AssetDocument.asset_id == listing.asset_id,
                )
            )
            valid_ids = {row[0] for row in valid_rows}
            invalid = [str(d) for d in doc_ids if d not in valid_ids]
            if invalid:
                raise BadRequestException(
                    f"Documents not found on this listing's asset: {', '.join(invalid)}",
                    code="INVALID_LISTING_DOCUMENTS",
                )
        meta[_PUBLIC_DOCS_KEY] = [str(d) for d in doc_ids]

    # JSONB columns don't track in-place mutation; reassign a new dict.
    listing.meta_data = meta


def _full_name(user: Optional[User]) -> str:
    """NULL-safe display name: 'First Last', falling back to email, then 'Unknown'."""
    if not user:
        return "Unknown"
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return name or user.email or "Unknown"


def _my_offer_item(offer: Offer, viewer_account_id, escrow_id=None) -> dict:
    """Serialize one offer for GET /offers/my from the viewer's perspective.

    role is "seller" when the viewer owns the listing (offer received),
    otherwise "buyer" (offer made). Callers must eager-load offer.account.user
    and offer.listing with its account.user, asset and asset.photos."""
    listing = offer.listing
    is_seller = listing is not None and listing.account_id == viewer_account_id
    counterparty_account = offer.account if is_seller else (listing.account if listing else None)
    counterparty_user = counterparty_account.user if counterparty_account else None

    asset = listing.asset if listing else None
    asset_type = None
    asset_thumbnail = None
    if asset is not None:
        if asset.asset_type:
            asset_type = getattr(asset.asset_type, "value", asset.asset_type)
        photo = _primary_photo(asset.photos)
        if photo is not None:
            asset_thumbnail = photo.thumbnail_url or photo.url

    return {
        "id": offer.id,
        "listing_id": offer.listing_id,
        "listing_title": listing.title if listing else None,
        "asset_type": asset_type,
        "asset_thumbnail": asset_thumbnail,
        "offer_amount": offer.offer_amount,
        "currency": offer.currency,
        "status": getattr(offer.status, "value", offer.status),
        "role": "seller" if is_seller else "buyer",
        "counterparty": _full_name(counterparty_user),
        "counterparty_id": counterparty_user.id if counterparty_user else None,
        "escrow_id": escrow_id,
        "message": offer.message,
        "created_at": offer.created_at,
        "updated_at": offer.updated_at or offer.created_at,
    }


class OfferCreate(BaseModel):
    offer_amount: Decimal
    currency: str = "USD"
    message: Optional[str] = None


@router.post("/listings", response_model=ListingResponse, status_code=status.HTTP_201_CREATED)
async def create_listing(
    listing_data: ListingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a marketplace listing (verified users only)"""
    from app.api.deps import get_account, get_user_subscription_plan
    from app.core.features import Feature, has_feature, get_limit, check_usage_limit
    from app.models.kyb import KYBVerification, KYBStatus
    from sqlalchemy import func
    
    if not current_user.is_verified:
        raise UnauthorizedException("User must be verified to create listings")
    
    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)
    
    # Check subscription feature
    if not has_feature(plan, Feature.MARKETPLACE_LIST):
        raise ForbiddenException("Marketplace listing creation requires a paid subscription")
    
    # Check KYB for corporate/trust accounts
    from app.services.account_restrictions_service import AccountRestrictionsService
    await AccountRestrictionsService.require_kyb_verification(db, account, "create marketplace listings")
    
    # Check usage limit — admins are exempt
    if current_user.role.value != "admin":
        active_listings_count = await db.execute(
            select(func.count(MarketplaceListing.id)).where(
                MarketplaceListing.account_id == account.id,
                MarketplaceListing.status == ListingStatus.ACTIVE
            )
        )
        current_count = active_listings_count.scalar() or 0
        if not check_usage_limit(plan, "listings", current_count):
            limit = get_limit(plan, "listings")
            raise ForbiddenException(f"Listing limit reached. Maximum {limit} active listings allowed for your plan.")
    
    # Verify asset belongs to account
    asset_result = await db.execute(
        select(Asset).where(
            and_(Asset.id == listing_data.asset_id, Asset.account_id == account.id)
        )
    )
    asset = asset_result.scalar_one_or_none()
    
    if not asset:
        raise NotFoundException("Asset", str(listing_data.asset_id))
    
    # Calculate listing fee (2%)
    listing_fee = calculate_listing_fee(listing_data.asking_price)
    
    listing = MarketplaceListing(
        account_id=account.id,
        asset_id=listing_data.asset_id,
        title=listing_data.title,
        description=listing_data.description,
        asking_price=listing_data.asking_price,
        currency=listing_data.currency,
        listing_fee=listing_fee,
        listing_fee_paid=False,
        status=ListingStatus.PENDING_APPROVAL,
    )
    await _apply_listing_details(listing, listing_data, db)

    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    
    logger.info(f"Listing created: {listing.id} by account {account.id}")
    return listing


PUBLIC_LISTING_STATUSES = [ListingStatus.APPROVED, ListingStatus.ACTIVE]


def _resolve_listing_status_filter(status_filter: Optional[ListingStatus], is_staff: bool) -> List[ListingStatus]:
    """Decide which listing statuses a caller may see on the public browse endpoint.

    Guests and non-staff users may only ever see publicly visible listings
    (APPROVED/ACTIVE). Only staff (APPROVE_LISTINGS) may filter to non-public
    statuses; otherwise a visitor could enumerate unapproved listings via
    ``?status_filter=pending_approval``. Returns the list of statuses to query,
    or raises 403 when a non-staff caller requests a non-public status.
    """
    if status_filter is None:
        return PUBLIC_LISTING_STATUSES
    if is_staff or status_filter in PUBLIC_LISTING_STATUSES:
        return [status_filter]
    raise ForbiddenException(
        "You can only filter marketplace listings by publicly visible statuses.",
        code="LISTING_STATUS_FILTER_FORBIDDEN",
    )


@public_router.get("/listings", response_model=Dict[str, Any])
async def list_listings(
    status_filter: Optional[ListingStatus] = Query(None),
    category: Optional[str] = Query(None, description="Canonical asset category name (see GET /assets/categories)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=1000, description="Items per page (frontend uses 20/50/100 presets; 1000 is an anti-scrape ceiling)"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """List marketplace listings with optional auth and pagination.

    Public: guests and non-staff only ever see APPROVED/ACTIVE listings, even when
    passing status_filter. Staff (APPROVE_LISTINGS) may filter to any status.
    """
    is_staff = bool(current_user) and has_permission(current_user.role, Permission.APPROVE_LISTINGS)
    statuses = _resolve_listing_status_filter(status_filter, is_staff)

    query = select(MarketplaceListing).where(MarketplaceListing.status.in_(statuses))
    count_query = select(func.count(MarketplaceListing.id)).where(MarketplaceListing.status.in_(statuses))

    if category:
        query = query.join(Asset, Asset.id == MarketplaceListing.asset_id).join(
            AssetCategory, AssetCategory.id == Asset.category_id
        ).where(func.lower(AssetCategory.name) == category.strip().lower())
        count_query = count_query.join(Asset, Asset.id == MarketplaceListing.asset_id).join(
            AssetCategory, AssetCategory.id == Asset.category_id
        ).where(func.lower(AssetCategory.name) == category.strip().lower())

    # Total count for pagination
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination (newest first)
    offset = (page - 1) * limit
    query = (
        query.options(_LISTING_ASSET_LOAD)
        .order_by(MarketplaceListing.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    listings = result.scalars().all()

    return {
        "data": [_listing_with_category(l) for l in listings],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit if total > 0 else 0,
        },
    }


class MyListingResponse(ListingResponse):
    # Count of PENDING offers awaiting the owner's response (badge on cards).
    pending_offers_count: int = 0


@public_router.get("/listings/my", response_model=Dict[str, Any])
async def get_my_listings(
    status_filter: Optional[ListingStatus] = Query(None),
    min_price: Optional[Decimal] = Query(None, ge=0),
    max_price: Optional[Decimal] = Query(None, ge=0),
    sort_by: Optional[str] = Query("created_at", description="Sort by: price, created_at"),
    sort_order: Optional[str] = Query(None, description="asc or desc. Defaults: price asc, created_at desc (newest first)"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_kyc_verified),
    db: AsyncSession = Depends(get_db),
):
    """The caller's own marketplace listings, any status, newest first.

    Owners may filter by ANY status (draft/pending_approval/rejected/... —
    it's their own data, unlike the public browse endpoint). Defined on
    public_router purely for route ordering: it must match before
    GET /listings/{listing_id}; auth + KYC are enforced by the
    require_kyc_verified dependency, same gate as the transact router."""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    if not account:
        raise NotFoundException("Account", str(current_user.id))

    conditions = [MarketplaceListing.account_id == account.id]
    if status_filter:
        conditions.append(MarketplaceListing.status == status_filter)
    if min_price is not None:
        conditions.append(MarketplaceListing.asking_price >= min_price)
    if max_price is not None:
        conditions.append(MarketplaceListing.asking_price <= max_price)

    total = (
        await db.execute(
            select(func.count(MarketplaceListing.id)).where(and_(*conditions))
        )
    ).scalar() or 0

    result = await db.execute(
        select(MarketplaceListing)
        .where(and_(*conditions))
        .options(_LISTING_ASSET_LOAD)
        .order_by(_listing_sort_clause(sort_by, sort_order))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    listings = result.scalars().all()

    pending_counts: Dict[Any, int] = {}
    if listings:
        count_rows = await db.execute(
            select(Offer.listing_id, func.count(Offer.id))
            .where(
                Offer.listing_id.in_([l.id for l in listings]),
                Offer.status == OfferStatus.PENDING,
            )
            .group_by(Offer.listing_id)
        )
        pending_counts = {listing_id: count for listing_id, count in count_rows}

    return {
        "data": [
            MyListingResponse(
                **_listing_with_category(l).model_dump(),
                pending_offers_count=pending_counts.get(l.id, 0),
            )
            for l in listings
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit if total > 0 else 0,
        },
    }


@public_router.get("/categories", response_model=Dict[str, Any])
async def list_marketplace_categories(
    db: AsyncSession = Depends(get_db)
):
    """Categories that currently have publicly visible listings (public, no auth).

    Returns only non-empty categories with their main category_group and listing
    count, so browse tabs/chips can be built without fetching listings.
    ``uncategorized`` counts public listings whose asset has no category (the
    frontend buckets these under "Others").
    """
    rows = (await db.execute(
        select(
            AssetCategory.name,
            AssetCategory.category_group,
            func.count(MarketplaceListing.id).label("count"),
        )
        .join(Asset, Asset.category_id == AssetCategory.id)
        .join(MarketplaceListing, MarketplaceListing.asset_id == Asset.id)
        .where(MarketplaceListing.status.in_(PUBLIC_LISTING_STATUSES))
        .group_by(AssetCategory.name, AssetCategory.category_group)
        .order_by(AssetCategory.category_group, AssetCategory.name)
    )).all()

    uncategorized = (await db.execute(
        select(func.count(MarketplaceListing.id))
        .join(Asset, Asset.id == MarketplaceListing.asset_id, isouter=True)
        .where(
            MarketplaceListing.status.in_(PUBLIC_LISTING_STATUSES),
            Asset.category_id.is_(None),
        )
    )).scalar() or 0

    return {
        "data": [
            {
                "category": name,
                "category_group": group.value if hasattr(group, "value") else group,
                "count": count,
            }
            for name, group, count in rows
        ],
        "uncategorized": uncategorized,
        "total": len(rows),
    }


def _require_categorized_asset(asset: Optional[Asset]) -> None:
    """A listing may only go public when its asset has a category — the browse
    UI is category-driven, so an uncategorized listing would be unreachable
    through every category tab/chip/filter."""
    if asset is None or asset.category_id is None:
        raise BadRequestException(
            "The listing's asset must have a category before it can be published to the marketplace.",
            code="LISTING_CATEGORY_REQUIRED",
        )


async def _assert_can_moderate_listing(db: AsyncSession, user: User, listing: MarketplaceListing) -> None:
    """Admins may moderate any listing; an advisor may moderate only listings owned
    by an investor assigned to them. Otherwise 403 LISTING_MODERATION_FORBIDDEN."""
    if has_permission(user.role, Permission.APPROVE_LISTINGS):
        return
    if user.role == Role.ADVISOR:
        from app.models.advisor_client import AdvisorClient
        owner = (await db.execute(
            select(Account).where(Account.id == listing.account_id)
        )).scalar_one_or_none()
        if owner:
            link = (await db.execute(
                select(AdvisorClient).where(
                    AdvisorClient.advisor_id == user.id,
                    AdvisorClient.client_id == owner.user_id,
                )
            )).scalar_one_or_none()
            if link:
                return
    raise ForbiddenException(
        "You can only moderate listings for your assigned clients.",
        code="LISTING_MODERATION_FORBIDDEN",
    )


async def _notify_listing_owner(db, listing, ntype, title, message):
    from app.services.notification_service import NotificationService
    try:
        await NotificationService.create_notification(
            db=db, account_id=listing.account_id, notification_type=ntype,
            title=title, message=message, send_email=False,
        )
    except Exception as e:
        logger.error(f"Failed to notify listing owner for {listing.id}: {e}")


@router.post("/listings/{listing_id}/approve", response_model=ListingResponse)
async def approve_listing(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Approve a listing -> it becomes publicly visible in the marketplace.

    Admins can approve any listing; an advisor can approve only listings owned by
    an assigned client.
    """
    result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
    )
    listing = result.scalar_one_or_none()
    if not listing:
        raise NotFoundException("Listing", str(listing_id))

    await _assert_can_moderate_listing(db, current_user, listing)

    asset = (await db.execute(
        select(Asset).where(Asset.id == listing.asset_id)
    )).scalar_one_or_none()
    _require_categorized_asset(asset)

    listing.status = ListingStatus.APPROVED
    listing.approved_by = current_user.id
    listing.approved_at = datetime.utcnow()
    listing.rejection_reason = None

    await db.commit()
    await db.refresh(listing)

    from app.models.notification import NotificationType
    await _notify_listing_owner(
        db, listing, NotificationType.LISTING_APPROVED,
        "Listing approved",
        f"Your listing '{listing.title}' has been approved and is now live in the marketplace.",
    )

    logger.info(f"Listing approved: {listing_id} by {current_user.id}")
    return listing


class RejectListingBody(BaseModel):
    reason: str


@router.post("/listings/{listing_id}/reject", response_model=ListingResponse)
async def reject_listing(
    listing_id: UUID,
    body: RejectListingBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject a listing with a reason. The reason is persisted on the listing
    (visible to owner, admin, and advisor) and the owner is notified."""
    if not body.reason or not body.reason.strip():
        raise BadRequestException("A rejection reason is required.")

    result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
    )
    listing = result.scalar_one_or_none()
    if not listing:
        raise NotFoundException("Listing", str(listing_id))

    await _assert_can_moderate_listing(db, current_user, listing)

    listing.status = ListingStatus.REJECTED
    listing.rejection_reason = body.reason.strip()

    await db.commit()
    await db.refresh(listing)

    from app.models.notification import NotificationType
    await _notify_listing_owner(
        db, listing, NotificationType.GENERAL,
        "Listing rejected",
        f"Your listing '{listing.title}' was rejected. Reason: {listing.rejection_reason}",
    )

    logger.info(f"Listing rejected: {listing_id} by {current_user.id}")
    return listing


@router.get("/approval-queue", response_model=Dict[str, Any])
async def listing_approval_queue(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pending-approval listings with reviewer-facing fields. Admins see all;
    advisors see only their assigned clients' listings."""
    is_admin = has_permission(current_user.role, Permission.APPROVE_LISTINGS)
    if not is_admin and current_user.role != Role.ADVISOR:
        raise ForbiddenException("Not permitted to view the approval queue.")

    from app.models.advisor_client import AdvisorClient
    Owner = aliased(User)
    AdvisorUser = aliased(User)

    q = (
        select(MarketplaceListing, Owner, AdvisorUser)
        .join(Account, MarketplaceListing.account_id == Account.id)
        .join(Owner, Account.user_id == Owner.id)
        .outerjoin(AdvisorClient, AdvisorClient.client_id == Owner.id)
        .outerjoin(AdvisorUser, AdvisorClient.advisor_id == AdvisorUser.id)
        .where(MarketplaceListing.status == ListingStatus.PENDING_APPROVAL)
    )
    if not is_admin:
        # advisor: restrict to listings owned by their assigned clients
        client_ids = (await db.execute(
            select(AdvisorClient.client_id).where(AdvisorClient.advisor_id == current_user.id)
        )).scalars().all()
        if not client_ids:
            return {"data": [], "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0}}
        q = q.where(Owner.id.in_(client_ids))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * limit
    rows = (await db.execute(
        q.order_by(MarketplaceListing.created_at.desc()).offset(offset).limit(limit)
    )).all()

    data = []
    for listing, owner, advisor_user in rows:
        owner_name = f"{owner.first_name or ''} {owner.last_name or ''}".strip() or owner.email
        data.append({
            "id": str(listing.id),
            "title": listing.title,
            "owner": {"id": str(owner.id), "name": owner_name, "email": owner.email},
            "asking_price": float(listing.asking_price) if listing.asking_price is not None else None,
            "currency": listing.currency,
            "status": listing.status.value,
            "submitted_at": listing.created_at.isoformat() if listing.created_at else None,
            "assigned_advisor": (
                {"id": str(advisor_user.id),
                 "name": (f"{advisor_user.first_name or ''} {advisor_user.last_name or ''}".strip() or advisor_user.email)}
                if advisor_user else None
            ),
        })

    return {
        "data": data,
        "pagination": {
            "page": page, "limit": limit, "total": total,
            "total_pages": (total + limit - 1) // limit if total else 0,
        },
    }


@router.post("/listings/{listing_id}/offers", status_code=status.HTTP_201_CREATED)
async def create_offer(
    listing_id: UUID,
    offer_data: OfferCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create an offer on a listing (the marketplace "Buy" action).

    Buyable statuses: APPROVED and ACTIVE. Staff (admin/advisor) cannot buy.
    Machine-readable error codes: STAFF_CANNOT_BUY, SUBSCRIPTION_REQUIRED,
    OFFER_LIMIT_REACHED, OWN_LISTING (plus KYC_REQUIRED from the router gate
    and 401 AUTH_REQUIRED when unauthenticated).
    """
    from app.api.deps import get_account, get_user_subscription_plan
    from app.core.features import Feature, has_feature, get_limit, check_usage_limit
    from sqlalchemy import func

    # Staff moderate the marketplace; they don't transact in it.
    if current_user.role.value in ("admin", "advisor"):
        raise ForbiddenException(
            "Admins and advisors cannot buy or make offers on listings.",
            code="STAFF_CANNOT_BUY",
        )

    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)

    # Check subscription feature (FREE tier can make offers but limited)
    if not has_feature(plan, Feature.MARKETPLACE_OFFER):
        raise ForbiddenException(
            "Making offers requires a subscription.",
            code="SUBSCRIPTION_REQUIRED",
        )

    # Check usage limit for offers
    pending_offers_count = await db.execute(
        select(func.count(Offer.id)).where(
            Offer.account_id == account.id,
            Offer.status == OfferStatus.PENDING
        )
    )
    current_count = pending_offers_count.scalar() or 0
    if not check_usage_limit(plan, "offers", current_count):
        limit = get_limit(plan, "offers")
        raise ForbiddenException(
            f"Offer limit reached. Maximum {limit} active offers allowed for your plan.",
            code="OFFER_LIMIT_REACHED",
        )

    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
    )
    listing = listing_result.scalar_one_or_none()

    # Both APPROVED (published) and ACTIVE listings are buyable.
    if not listing or listing.status not in (ListingStatus.APPROVED, ListingStatus.ACTIVE):
        raise NotFoundException("Listing", str(listing_id))

    if listing.account_id == account.id:
        raise ForbiddenException(
            "You cannot make an offer on your own listing.",
            code="OWN_LISTING",
        )
    
    offer = Offer(
        listing_id=listing_id,
        account_id=account.id,
        offer_amount=offer_data.offer_amount,
        currency=offer_data.currency,
        message=offer_data.message,
        status=OfferStatus.PENDING,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    
    db.add(offer)
    await db.commit()
    await db.refresh(offer)
    
    logger.info(f"Offer created: {offer.id} on listing {listing_id}")
    return offer


@router.post("/offers/{offer_id}/accept")
async def accept_offer(
    offer_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Accept an offer and create escrow"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    offer_result = await db.execute(
        select(Offer).where(Offer.id == offer_id)
    )
    offer = offer_result.scalar_one_or_none()
    
    if not offer:
        raise NotFoundException("Offer", str(offer_id))
    
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == offer.listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    
    if listing.account_id != account.id:
        raise UnauthorizedException("Only listing owner can accept offers")
    
    if offer.status != OfferStatus.PENDING:
        raise BadRequestException("Offer is not pending")
    
    # Calculate commission (20% standard, 10% premium)
    is_premium = current_user.role == Role.ADMIN  # Premium logic
    commission = calculate_commission(offer.offer_amount, is_premium)
    
    # Create escrow transaction
    escrow = EscrowTransaction(
        listing_id=listing.id,
        offer_id=offer.id,
        buyer_id=offer.account_id,
        seller_id=account.id,
        amount=offer.offer_amount,
        currency=offer.currency,
        commission=commission,
        status=EscrowStatus.PENDING,
    )
    
    # Create Stripe payment intent
    try:
        payment_intent = StripeClient.create_payment_intent(
            amount=int(offer.offer_amount * 100),  # Convert to cents
            currency=offer.currency.lower(),
            metadata={
                "escrow_id": str(escrow.id),
                "listing_id": str(listing.id),
                "offer_id": str(offer.id),
            }
        )
        escrow.stripe_payment_intent_id = payment_intent["id"]
    except Exception as e:
        logger.error(f"Failed to create payment intent: {e}")
        raise BadRequestException("Failed to create payment intent")
    
    offer.status = OfferStatus.ACCEPTED
    listing.status = ListingStatus.SOLD
    
    db.add(escrow)
    await db.commit()
    await db.refresh(escrow)
    
    logger.info(f"Offer accepted: {offer_id}, escrow created: {escrow.id}")
    return {
        "escrow_id": escrow.id,
        "payment_intent_id": escrow.stripe_payment_intent_id,
        "amount": float(escrow.amount),
        "commission": float(escrow.commission),
    }


@router.post("/escrow/{escrow_id}/release")
async def release_escrow(
    escrow_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Release escrow funds to seller"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    escrow_result = await db.execute(
        select(EscrowTransaction).where(EscrowTransaction.id == escrow_id)
    )
    escrow = escrow_result.scalar_one_or_none()
    
    if not escrow:
        raise NotFoundException("Escrow", str(escrow_id))
    
    if escrow.seller_id != account.id:
        raise UnauthorizedException("Only seller can release escrow")
    
    if escrow.status != EscrowStatus.FUNDED:
        raise BadRequestException("Escrow must be funded before release")
    
    escrow.status = EscrowStatus.RELEASED
    escrow.released_at = datetime.utcnow()
    
    await db.commit()
    
    logger.info(f"Escrow released: {escrow_id}")
    return {"message": "Escrow released successfully"}


class ListingUpdate(ListingDetailFields):
    title: Optional[str] = None
    description: Optional[str] = None
    asking_price: Optional[Decimal] = None


class OfferResponse(BaseModel):
    id: UUID
    offer_amount: Decimal
    currency: str
    status: str
    message: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class EscrowResponse(BaseModel):
    id: UUID
    amount: Decimal
    currency: str
    commission: Optional[Decimal] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


async def _visible_listing_or_404(
    listing_id: UUID,
    current_user: Optional[User],
    db: AsyncSession,
) -> tuple[MarketplaceListing, bool]:
    """Load a listing for detail-page reads and enforce visibility: public for
    APPROVED/ACTIVE; non-public listings are visible only to staff and the
    owning account (404 otherwise). Returns (listing, is_owner)."""
    result = await db.execute(
        select(MarketplaceListing)
        .options(
            _LISTING_ASSET_LOAD,
            selectinload(MarketplaceListing.account).selectinload(Account.user),
        )
        .where(MarketplaceListing.id == listing_id)
    )
    listing = result.scalar_one_or_none()

    if not listing:
        raise NotFoundException("Listing", str(listing_id))

    is_owner = False
    if current_user:
        account = (await db.execute(
            select(Account).where(Account.user_id == current_user.id)
        )).scalar_one_or_none()
        is_owner = bool(account) and account.id == listing.account_id

    if listing.status not in (ListingStatus.APPROVED, ListingStatus.ACTIVE):
        is_staff = bool(current_user) and has_permission(current_user.role, Permission.APPROVE_LISTINGS)
        if not (is_staff or is_owner):
            raise NotFoundException("Listing", str(listing_id))

    return listing, is_owner


@public_router.get("/listings/{listing_id}", response_model=ListingDetailResponse)
async def get_listing(
    listing_id: UUID,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Get listing details. Public for APPROVED/ACTIVE listings; non-public
    listings are visible only to staff and the owning account (404 otherwise)."""
    listing, is_owner = await _visible_listing_or_404(listing_id, current_user, db)
    return _listing_detail_response(listing, is_owner)


_PERFORMANCE_RANGES = {"30d": 30, "90d": 90, "1y": 365, "all": None}


def _bucket_series(points, granularity: str):
    """Collapse [(datetime, value)] (sorted asc) to the LAST point per
    daily/weekly/monthly bucket. Pure; unit-tested without a DB."""
    def key(dt):
        if granularity == "monthly":
            return (dt.year, dt.month)
        if granularity == "weekly":
            iso = dt.isocalendar()
            return (iso[0], iso[1])
        return dt.date()

    out, last_key = [], None
    for dt, value in points:
        k = key(dt)
        if k == last_key:
            out[-1] = (dt, value)
        else:
            out.append((dt, value))
            last_key = k
    return out


def _performance_metrics(points) -> dict:
    """Return/volatility metrics over [(datetime, value)] sorted asc.
    Fewer than 2 points (or a non-positive start) yields zeros. Pure."""
    zeros = {
        "total_return_pct": 0.0,
        "annualized_return_pct": 0.0,
        "volatility_pct": 0.0,
        "value_change_abs": 0.0,
    }
    if len(points) < 2:
        return zeros
    (first_dt, first_v), (last_dt, last_v) = points[0], points[-1]
    if first_v <= 0:
        return zeros

    total_return = (last_v / first_v - 1) * 100
    days = max((last_dt - first_dt).days, 1)
    # Annualizing a short window compounds noise into absurd numbers
    # (real case: +846% in 30 days -> 1.9e14% annualized). Under 90 days
    # report null and let the UI hide the tile.
    annualized = ((last_v / first_v) ** (365.0 / days) - 1) * 100 if days >= 90 else None

    returns = [
        points[i][1] / points[i - 1][1] - 1
        for i in range(1, len(points))
        if points[i - 1][1] > 0
    ]
    volatility = 0.0
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        volatility = (sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5 * 100

    return {
        "total_return_pct": round(total_return, 2),
        "annualized_return_pct": round(annualized, 2) if annualized is not None else None,
        "volatility_pct": round(volatility, 2),
        "value_change_abs": round(last_v - first_v, 2),
    }


@public_router.get("/listings/{listing_id}/performance")
async def get_listing_performance(
    listing_id: UUID,
    time_range: str = Query("1y", description="30d, 90d, 1y, all"),
    granularity: str = Query("daily", description="daily, weekly, monthly"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Value history of the listing's underlying asset for the Performance tab.

    Series comes from asset_valuations; when an asset has no valuation rows
    yet, falls back to the two real anchor points we do have (purchase price
    at acquisition date -> current value now). Empty series when neither
    exists — the frontend renders an empty state."""
    if time_range not in _PERFORMANCE_RANGES:
        raise BadRequestException(
            f"Invalid time_range. Must be one of: {', '.join(_PERFORMANCE_RANGES)}")
    if granularity not in ("daily", "weekly", "monthly"):
        raise BadRequestException("Invalid granularity. Must be one of: daily, weekly, monthly")

    listing, _ = await _visible_listing_or_404(listing_id, current_user, db)

    days = _PERFORMANCE_RANGES[time_range]
    start_date = datetime.now(dt_timezone.utc) - timedelta(days=days) if days else None

    valuation_query = (
        select(AssetValuation)
        .where(AssetValuation.asset_id == listing.asset_id)
        .order_by(AssetValuation.valuation_date.asc())
    )
    if start_date:
        valuation_query = valuation_query.where(AssetValuation.valuation_date >= start_date)
    valuations = (await db.execute(valuation_query)).scalars().all()

    points = [(v.valuation_date, float(v.value)) for v in valuations]

    asset = listing.asset
    if not points and asset is not None and asset.current_value is not None:
        now = datetime.now(dt_timezone.utc)
        if asset.purchase_price and asset.acquisition_date:
            points = [
                (asset.acquisition_date, float(asset.purchase_price)),
                (now, float(asset.current_value)),
            ]
        else:
            points = [(now, float(asset.current_value))]

    bucketed = _bucket_series(points, granularity)
    metrics = _performance_metrics(bucketed)
    metrics["currency"] = (asset.currency if asset is not None else None) or listing.currency

    return {
        "metrics": metrics,
        "series": [
            {"date": dt.date().isoformat(), "value": value}
            for dt, value in bucketed
        ],
        "time_range": time_range,
        "granularity": granularity,
    }


def _document_file_type(doc: AssetDocument) -> Optional[str]:
    """Short file-type label ('pdf', 'docx', ...) from mime type or filename."""
    mime_map = {
        "application/pdf": "pdf",
        "application/msword": "doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.ms-excel": "xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "image/jpeg": "jpg",
        "image/png": "png",
    }
    if doc.mime_type:
        mapped = mime_map.get(doc.mime_type.lower())
        if mapped:
            return mapped
    if doc.file_name and "." in doc.file_name:
        return doc.file_name.rsplit(".", 1)[1].lower()
    if doc.mime_type and "/" in doc.mime_type:
        return doc.mime_type.rsplit("/", 1)[1].lower()
    return None


@public_router.get("/listings/{listing_id}/documents")
async def get_listing_documents(
    listing_id: UUID,
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Documents the seller explicitly exposed on this listing (Documents tab).

    Only AssetDocuments whose ids the seller attached via document_ids on
    listing create/update are returned — the owner's other files stay
    private, since any authenticated buyer (or guest) can reach this page."""
    listing, _ = await _visible_listing_or_404(listing_id, current_user, db)

    raw_ids = (listing.meta_data or {}).get(_PUBLIC_DOCS_KEY) or []
    public_ids = []
    for raw in raw_ids:
        try:
            public_ids.append(UUID(str(raw)))
        except ValueError:
            continue
    if not public_ids:
        return {"data": []}

    docs = (await db.execute(
        select(AssetDocument)
        .where(
            AssetDocument.id.in_(public_ids),
            AssetDocument.asset_id == listing.asset_id,
        )
        .order_by(AssetDocument.created_at.desc())
    )).scalars().all()

    return {
        "data": [
            {
                "id": doc.id,
                "name": doc.name or doc.file_name,
                "file_type": _document_file_type(doc),
                "size_bytes": doc.file_size,
                "url": doc.url,
                "uploaded_at": doc.created_at,
            }
            for doc in docs
        ]
    }


@router.put("/listings/{listing_id}", response_model=ListingResponse)
async def update_listing(
    listing_id: UUID,
    listing_data: ListingUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a listing"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(MarketplaceListing).where(
            MarketplaceListing.id == listing_id,
            MarketplaceListing.account_id == account.id
        )
    )
    listing = result.scalar_one_or_none()
    
    if not listing:
        raise NotFoundException("Listing", str(listing_id))
    
    if listing.status not in [ListingStatus.DRAFT, ListingStatus.PENDING_APPROVAL]:
        raise BadRequestException("Can only update draft or pending listings")
    
    if listing_data.title:
        listing.title = listing_data.title
    if listing_data.description is not None:
        listing.description = listing_data.description
    if listing_data.asking_price:
        listing.asking_price = listing_data.asking_price
        # Recalculate listing fee
        listing.listing_fee = calculate_listing_fee(listing_data.asking_price)
    await _apply_listing_details(listing, listing_data, db)

    await db.commit()
    await db.refresh(listing)
    
    logger.info(f"Listing updated: {listing_id}")
    return listing


@router.delete("/listings/{listing_id}")
async def delete_listing(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel/delete a listing"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(MarketplaceListing).where(
            MarketplaceListing.id == listing_id,
            MarketplaceListing.account_id == account.id
        )
    )
    listing = result.scalar_one_or_none()
    
    if not listing:
        raise NotFoundException("Listing", str(listing_id))
    
    # Check if there are active offers
    active_offers_result = await db.execute(
        select(Offer).where(
            Offer.listing_id == listing_id,
            Offer.status == OfferStatus.PENDING
        )
    )
    if active_offers_result.scalars().first():
        raise BadRequestException("Cannot delete listing with active offers")
    
    listing.status = ListingStatus.CANCELLED
    await db.commit()
    
    logger.info(f"Listing cancelled: {listing_id}")
    return {"message": "Listing cancelled successfully"}


@router.post("/listings/{listing_id}/activate", response_model=ListingResponse)
async def activate_listing(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Activate a listing"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(MarketplaceListing).where(
            MarketplaceListing.id == listing_id,
            MarketplaceListing.account_id == account.id
        )
    )
    listing = result.scalar_one_or_none()
    
    if not listing:
        raise NotFoundException("Listing", str(listing_id))
    
    if listing.status != ListingStatus.APPROVED:
        raise BadRequestException("Only approved listings can be activated")
    
    if not listing.listing_fee_paid:
        raise BadRequestException("Listing fee must be paid before activation")
    
    listing.status = ListingStatus.ACTIVE
    await db.commit()
    await db.refresh(listing)
    
    logger.info(f"Listing activated: {listing_id}")
    return listing


@router.post("/listings/{listing_id}/pay-fee")
async def pay_listing_fee(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Pay listing fee"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    result = await db.execute(
        select(MarketplaceListing).where(
            MarketplaceListing.id == listing_id,
            MarketplaceListing.account_id == account.id
        )
    )
    listing = result.scalar_one_or_none()
    
    if not listing:
        raise NotFoundException("Listing", str(listing_id))
    
    if listing.listing_fee_paid:
        raise BadRequestException("Listing fee already paid")
    
    if not listing.listing_fee:
        raise BadRequestException("No listing fee calculated")
    
    # Create payment intent
    try:
        payment_intent = StripeClient.create_payment_intent(
            amount=int(listing.listing_fee * 100),
            currency=listing.currency.lower(),
            metadata={
                "account_id": str(account.id),
                "listing_id": str(listing.id),
                "type": "listing_fee",
            }
        )
        
        listing.listing_fee_paid = True
        await db.commit()
        
        return {
            "payment_intent_id": payment_intent["id"],
            "amount": float(listing.listing_fee),
            "currency": listing.currency
        }
    except Exception as e:
        logger.error(f"Failed to create payment intent: {e}")
        raise BadRequestException("Failed to create payment intent")


@router.get("/listings/{listing_id}/offers", response_model=List[OfferResponse])
async def list_offers(
    listing_id: UUID,
    status_filter: Optional[OfferStatus] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List offers for a listing"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    
    if not listing:
        raise NotFoundException("Listing", str(listing_id))
    
    # Only listing owner can see all offers
    if listing.account_id != account.id:
        raise UnauthorizedException("Only listing owner can view offers")
    
    query = select(Offer).where(Offer.listing_id == listing_id)
    if status_filter:
        query = query.where(Offer.status == status_filter)
    
    result = await db.execute(query.order_by(Offer.created_at.desc()))
    offers = result.scalars().all()
    
    return offers


@router.get("/offers/my")
async def get_my_offers(
    status_filter: Optional[OfferStatus] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Offer history for the current user, both sides: offers they made on
    other accounts' listings (role "buyer") and offers received on listings
    they own (role "seller")."""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    query = (
        select(Offer)
        .join(MarketplaceListing, MarketplaceListing.id == Offer.listing_id)
        .where(
            or_(
                Offer.account_id == account.id,
                MarketplaceListing.account_id == account.id,
            )
        )
        .options(
            selectinload(Offer.account).selectinload(Account.user),
            selectinload(Offer.listing).options(
                selectinload(MarketplaceListing.account).selectinload(Account.user),
                selectinload(MarketplaceListing.asset).selectinload(Asset.photos),
            ),
        )
    )
    if status_filter:
        query = query.where(Offer.status == status_filter)

    result = await db.execute(query.order_by(Offer.created_at.desc()))
    offers = result.scalars().all()

    # Escrow ids let the UI open escrow management from an accepted offer.
    escrow_by_offer = {}
    if offers:
        escrow_rows = await db.execute(
            select(EscrowTransaction.offer_id, EscrowTransaction.id)
            .where(EscrowTransaction.offer_id.in_([o.id for o in offers]))
            .order_by(EscrowTransaction.created_at)  # latest escrow wins below
        )
        escrow_by_offer = {offer_id: escrow_id for offer_id, escrow_id in escrow_rows}

    return {
        "data": [
            _my_offer_item(offer, account.id, escrow_by_offer.get(offer.id))
            for offer in offers
        ]
    }


@router.get("/offers/{offer_id}", response_model=OfferResponse)
async def get_offer(
    offer_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get offer details"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    result = await db.execute(
        select(Offer).where(Offer.id == offer_id)
    )
    offer = result.scalar_one_or_none()
    
    if not offer:
        raise NotFoundException("Offer", str(offer_id))
    
    # Check access - buyer or seller can view
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == offer.listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    
    if offer.account_id != account.id and listing.account_id != account.id:
        raise UnauthorizedException("Access denied")
    
    return offer


@router.post("/offers/{offer_id}/reject")
async def reject_offer(
    offer_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Reject an offer"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    offer_result = await db.execute(
        select(Offer).where(Offer.id == offer_id)
    )
    offer = offer_result.scalar_one_or_none()
    
    if not offer:
        raise NotFoundException("Offer", str(offer_id))
    
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == offer.listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    
    if listing.account_id != account.id:
        raise UnauthorizedException("Only listing owner can reject offers")
    
    if offer.status != OfferStatus.PENDING:
        raise BadRequestException("Only pending offers can be rejected")
    
    offer.status = OfferStatus.REJECTED
    await db.commit()
    
    logger.info(f"Offer rejected: {offer_id}")
    return {"message": "Offer rejected successfully"}


@router.post("/offers/{offer_id}/counter")
async def counter_offer(
    offer_id: UUID,
    counter_amount: Decimal = Body(...),
    message: Optional[str] = Body(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a counter offer"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    offer_result = await db.execute(
        select(Offer).where(Offer.id == offer_id)
    )
    original_offer = offer_result.scalar_one_or_none()
    
    if not original_offer:
        raise NotFoundException("Offer", str(offer_id))
    
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == original_offer.listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    
    if listing.account_id != account.id:
        raise UnauthorizedException("Only listing owner can counter offers")
    
    if original_offer.status != OfferStatus.PENDING:
        raise BadRequestException("Can only counter pending offers")
    
    # Mark original as countered
    original_offer.status = OfferStatus.COUNTERED
    
    # Create new counter offer
    counter_offer = Offer(
        listing_id=original_offer.listing_id,
        account_id=account.id,  # Seller's account
        offer_amount=counter_amount,
        currency=original_offer.currency,
        message=message or f"Counter offer for {original_offer.offer_amount}",
        status=OfferStatus.PENDING,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    
    db.add(counter_offer)
    await db.commit()
    await db.refresh(counter_offer)
    
    logger.info(f"Counter offer created: {counter_offer.id}")
    return {"message": "Counter offer created", "offer_id": counter_offer.id}


@router.post("/offers/{offer_id}/withdraw")
async def withdraw_offer(
    offer_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Withdraw an offer"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    offer_result = await db.execute(
        select(Offer).where(
            Offer.id == offer_id,
            Offer.account_id == account.id
        )
    )
    offer = offer_result.scalar_one_or_none()
    
    if not offer:
        raise NotFoundException("Offer", str(offer_id))
    
    if offer.status != OfferStatus.PENDING:
        raise BadRequestException("Only pending offers can be withdrawn")
    
    offer.status = OfferStatus.WITHDRAWN
    await db.commit()
    
    logger.info(f"Offer withdrawn: {offer_id}")
    return {"message": "Offer withdrawn successfully"}


@router.get("/escrow/{escrow_id}", response_model=EscrowResponse)
async def get_escrow(
    escrow_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get escrow details"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    escrow_result = await db.execute(
        select(EscrowTransaction).where(EscrowTransaction.id == escrow_id)
    )
    escrow = escrow_result.scalar_one_or_none()
    
    if not escrow:
        raise NotFoundException("Escrow", str(escrow_id))
    
    # Check access - buyer or seller
    if escrow.buyer_id != account.id and escrow.seller_id != account.id:
        raise UnauthorizedException("Access denied")
    
    return escrow


@router.post("/escrow/{escrow_id}/fund")
async def fund_escrow(
    escrow_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark escrow as funded (called after payment intent succeeds)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    escrow_result = await db.execute(
        select(EscrowTransaction).where(EscrowTransaction.id == escrow_id)
    )
    escrow = escrow_result.scalar_one_or_none()
    
    if not escrow:
        raise NotFoundException("Escrow", str(escrow_id))
    
    if escrow.buyer_id != account.id:
        raise UnauthorizedException("Only buyer can fund escrow")
    
    if escrow.status != EscrowStatus.PENDING:
        raise BadRequestException("Escrow is not in pending status")
    
    escrow.status = EscrowStatus.FUNDED
    await db.commit()
    
    logger.info(f"Escrow funded: {escrow_id}")
    return {"message": "Escrow funded successfully"}


@router.post("/escrow/{escrow_id}/dispute")
async def create_dispute(
    escrow_id: UUID,
    reason: str = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a dispute for escrow"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    escrow_result = await db.execute(
        select(EscrowTransaction).where(EscrowTransaction.id == escrow_id)
    )
    escrow = escrow_result.scalar_one_or_none()
    
    if not escrow:
        raise NotFoundException("Escrow", str(escrow_id))
    
    # Buyer or seller can create dispute
    if escrow.buyer_id != account.id and escrow.seller_id != account.id:
        raise UnauthorizedException("Access denied")
    
    if escrow.status != EscrowStatus.FUNDED:
        raise BadRequestException("Can only dispute funded escrow")
    
    escrow.status = EscrowStatus.DISPUTED
    # Store dispute reason in metadata if available
    await db.commit()

    logger.info(f"Escrow dispute created: {escrow_id}")

    # Notify admins of the new dispute
    try:
        from app.services.notification_service import NotificationService
        from app.models.notification import NotificationType
        await NotificationService.notify_admins(
            db=db,
            notification_type=NotificationType.GENERAL,
            title="New Dispute Filed",
            message=f"A dispute was filed on escrow {escrow_id}." + (f" Reason: {reason}" if reason else ""),
            metadata=f'{{"escrow_id": "{escrow_id}", "event": "dispute_created"}}',
        )
    except Exception as e:
        logger.error(f"Failed to notify admins of dispute {escrow_id}: {e}")

    return {"message": "Dispute created successfully", "reason": reason}


@router.post("/escrow/{escrow_id}/refund")
async def refund_escrow(
    escrow_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Refund escrow to buyer"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    escrow_result = await db.execute(
        select(EscrowTransaction).where(EscrowTransaction.id == escrow_id)
    )
    escrow = escrow_result.scalar_one_or_none()
    
    if not escrow:
        raise NotFoundException("Escrow", str(escrow_id))
    
    # Only seller or admin can refund
    if escrow.seller_id != account.id:
        # Check if admin
        from app.core.permissions import Role, Permission, has_permission
        if not has_permission(current_user.role, Permission.MANAGE_MARKETPLACE):
            raise UnauthorizedException("Only seller or admin can refund escrow")
    
    if escrow.status not in [EscrowStatus.FUNDED, EscrowStatus.DISPUTED]:
        raise BadRequestException("Can only refund funded or disputed escrow")
    
    # Refund via Stripe if payment intent exists
    if escrow.stripe_payment_intent_id:
        try:
            # Get payment intent to find charge
            import stripe
            payment_intent = stripe.PaymentIntent.retrieve(escrow.stripe_payment_intent_id)
            if payment_intent.charges.data:
                charge_id = payment_intent.charges.data[0].id
                StripeClient.create_refund(charge_id)
        except Exception as e:
            logger.error(f"Failed to refund via Stripe: {e}")
    
    escrow.status = EscrowStatus.REFUNDED
    await db.commit()
    
    logger.info(f"Escrow refunded: {escrow_id}")
    return {"message": "Escrow refunded successfully"}


def _resolve_category_group(value: str) -> CategoryGroup:
    """Match a category_group query param to the CategoryGroup enum,
    case-insensitively. Raises 400 with the valid values on no match."""
    for group in CategoryGroup:
        if group.value.lower() == value.strip().lower():
            return group
    raise BadRequestException(
        f"Invalid category_group '{value}'. Must be one of: "
        f"{', '.join(g.value for g in CategoryGroup)}",
        code="INVALID_CATEGORY_GROUP",
    )


def _listing_sort_clause(sort_by: Optional[str], sort_order: Optional[str]):
    """Sort clause for /search. Without an explicit sort_order the historical
    defaults hold (price ascending, created_at newest-first) so existing
    consumers keep their ordering."""
    column = (
        MarketplaceListing.asking_price
        if sort_by == "price"
        else MarketplaceListing.created_at
    )
    if sort_order is None:
        return column.asc() if sort_by == "price" else column.desc()
    order = sort_order.strip().lower()
    if order == "asc":
        return column.asc()
    if order == "desc":
        return column.desc()
    raise BadRequestException(
        f"Invalid sort_order '{sort_order}'. Must be 'asc' or 'desc'.",
        code="INVALID_SORT_ORDER",
    )


@public_router.get("/search", response_model=Dict[str, Any])
async def search_listings(
    q: Optional[str] = Query(None, description="Search query"),
    asset_type: Optional[str] = Query(
        None,
        deprecated=True,
        description="DEPRECATED (frontend no longer sends this): legacy asset type filter. Use category/category_group instead. Slated for removal after a usage-log quiet period.",
    ),
    category: Optional[str] = Query(None, description="Canonical asset category name (see GET /assets/categories)"),
    category_group: Optional[str] = Query(None, description="Main category group (Assets, Portfolio, Liabilities, ...)"),
    min_price: Optional[Decimal] = Query(None),
    max_price: Optional[Decimal] = Query(None),
    sort_by: Optional[str] = Query("created_at", description="Sort by: price, created_at"),
    sort_order: Optional[str] = Query(None, description="asc or desc. Defaults: price asc, created_at desc"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=1000, description="Items per page (frontend uses 20/50/100 presets; 1000 is an anti-scrape ceiling)"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Search marketplace listings (public, paginated).

    Guests can search/browse; only approved/active listings are returned.
    """
    # Base query: only approved/active listings
    base_status_filter = [ListingStatus.APPROVED, ListingStatus.ACTIVE]
    query = select(MarketplaceListing).where(
        MarketplaceListing.status.in_(base_status_filter)
    )
    count_query = select(func.count(MarketplaceListing.id)).where(
        MarketplaceListing.status.in_(base_status_filter)
    )

    # Free‑text search
    if q:
        search_expr = f"%{q}%"
        text_filter = or_(
            MarketplaceListing.title.ilike(search_expr),
            MarketplaceListing.description.ilike(search_expr)
        )
        query = query.where(text_filter)
        count_query = count_query.where(text_filter)

    # Filter by asset type, canonical category and/or main category group
    # (join Asset once, AssetCategory once)
    if asset_type or category or category_group:
        query = query.join(Asset, Asset.id == MarketplaceListing.asset_id)
        count_query = count_query.join(Asset, Asset.id == MarketplaceListing.asset_id)
        if asset_type:
            # Deprecated 2026-07-05 (frontend removed its Asset Type checkboxes).
            # Log callers so we know when it's safe to remove the param for good.
            logger.warning(f"Deprecated asset_type filter used on /marketplace/search: {asset_type!r}")
            query = query.where(Asset.asset_type == asset_type)
            count_query = count_query.where(Asset.asset_type == asset_type)
        if category or category_group:
            query = query.join(AssetCategory, AssetCategory.id == Asset.category_id)
            count_query = count_query.join(AssetCategory, AssetCategory.id == Asset.category_id)
            if category:
                category_filter = func.lower(AssetCategory.name) == category.strip().lower()
                query = query.where(category_filter)
                count_query = count_query.where(category_filter)
            if category_group:
                group_filter = AssetCategory.category_group == _resolve_category_group(category_group)
                query = query.where(group_filter)
                count_query = count_query.where(group_filter)

    # Price range filters
    if min_price is not None:
        price_min_filter = MarketplaceListing.asking_price >= min_price
        query = query.where(price_min_filter)
        count_query = count_query.where(price_min_filter)

    if max_price is not None:
        price_max_filter = MarketplaceListing.asking_price <= max_price
        query = query.where(price_max_filter)
        count_query = count_query.where(price_max_filter)

    # Sorting
    query = query.order_by(_listing_sort_clause(sort_by, sort_order))

    # Pagination
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    offset = (page - 1) * limit
    query = query.options(_LISTING_ASSET_LOAD).offset(offset).limit(limit)

    result = await db.execute(query)
    listings = result.scalars().all()

    return {
        "data": [_listing_with_category(l) for l in listings],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit if total > 0 else 0,
        },
    }


# ==================== Market Highlights APIs ====================

class MarketHighlightResponse(BaseModel):
    category: str
    name: str
    value: str
    value_numeric: float
    is_positive: bool
    change_percentage: float
    trend: str
    updated_at: datetime


class MarketHighlightsResponse(BaseModel):
    highlights: List[MarketHighlightResponse]
    last_updated: datetime
    time_range: str


@public_router.get("/market-highlights", response_model=MarketHighlightsResponse)
async def get_market_highlights(
    time_range: Optional[str] = Query("1d", description="Time range: 1d, 7d, 30d, 90d, 1y, all"),
    categories: Optional[str] = Query(None, description="Comma-separated categories"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Get market highlights showing performance trends for different asset categories"""
    from app.models.asset import Asset, AssetCategory
    
    # Validate time_range
    valid_ranges = ["1d", "7d", "30d", "90d", "1y", "all"]
    if time_range not in valid_ranges:
        raise BadRequestException(f"Invalid time_range. Must be one of: {', '.join(valid_ranges)}")
    
    # Calculate date range
    now = datetime.utcnow()
    if time_range == "1d":
        start_date = now - timedelta(days=1)
    elif time_range == "7d":
        start_date = now - timedelta(days=7)
    elif time_range == "30d":
        start_date = now - timedelta(days=30)
    elif time_range == "90d":
        start_date = now - timedelta(days=90)
    elif time_range == "1y":
        start_date = now - timedelta(days=365)
    else:  # all
        start_date = None
    
    # Parse categories filter
    category_list = None
    if categories:
        category_list = [c.strip() for c in categories.split(",")]
    
    # Get listings in the time range
    query = select(MarketplaceListing).join(Asset).join(AssetCategory, isouter=True)
    if start_date:
        query = query.where(MarketplaceListing.created_at >= start_date)
    query = query.where(MarketplaceListing.status.in_([ListingStatus.ACTIVE, ListingStatus.SOLD]))
    
    result = await db.execute(query)
    listings = result.scalars().all()
    
    # Group by category and calculate changes
    category_data = {}
    for listing in listings:
        # Get category name from asset
        asset_result = await db.execute(
            select(Asset).where(Asset.id == listing.asset_id)
        )
        asset = asset_result.scalar_one_or_none()
        if not asset:
            continue
        
        category_name = "Other"
        if asset.category:
            category_result = await db.execute(
                select(AssetCategory).where(AssetCategory.id == asset.category_id)
            )
            category_obj = category_result.scalar_one_or_none()
            if category_obj:
                category_name = category_obj.name
        
        # Filter by categories if specified
        if category_list and category_name not in category_list:
            continue
        
        if category_name not in category_data:
            category_data[category_name] = {
                "prices": [],
                "current_prices": []
            }
        
        # Get historical price (simplified - using current price as baseline)
        category_data[category_name]["current_prices"].append(float(listing.asking_price))
    
    # Calculate highlights
    highlights = []
    for category_name, data in category_data.items():
        if not data["current_prices"]:
            continue
        
        # Calculate average price change (simplified calculation)
        # In production, you'd compare historical averages
        avg_price = sum(data["current_prices"]) / len(data["current_prices"])
        
        # Simulate price change (in production, compare with historical data)
        # For now, use a deterministic change based on category hash
        # This ensures consistent results for the same category
        category_hash = hash(category_name) % 100
        change_pct = round((category_hash - 50) / 20.0, 1)  # Range: -2.5 to 2.5
        
        is_positive = change_pct >= 0
        trend = "up" if change_pct > 0.5 else "down" if change_pct < -0.5 else "neutral"
        value_str = f"{'+' if is_positive else ''}{change_pct:.1f}%"
        
        highlights.append(MarketHighlightResponse(
            category=category_name,
            name=category_name,
            value=value_str,
            value_numeric=change_pct,
            is_positive=is_positive,
            change_percentage=change_pct,
            trend=trend,
            updated_at=now
        ))
    
    return MarketHighlightsResponse(
        highlights=highlights,
        last_updated=now,
        time_range=time_range
    )


class TrendDataPoint(BaseModel):
    date: datetime
    value: float
    category: Optional[str] = None


class MarketTrendsResponse(BaseModel):
    trends: List[TrendDataPoint]
    time_range: str
    granularity: str
    summary: dict


@public_router.get("/market-trends", response_model=MarketTrendsResponse)
async def get_market_trends(
    time_range: Optional[str] = Query("30d", description="Time range: 7d, 30d, 90d, 1y, all"),
    category: Optional[str] = Query(None),
    granularity: Optional[str] = Query("daily", description="hourly, daily, weekly, monthly"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Get historical market trend data for chart visualization"""
    from app.models.asset import Asset, AssetCategory
    
    # Validate parameters
    valid_ranges = ["7d", "30d", "90d", "1y", "all"]
    if time_range not in valid_ranges:
        raise BadRequestException(f"Invalid time_range. Must be one of: {', '.join(valid_ranges)}")
    
    valid_granularities = ["hourly", "daily", "weekly", "monthly"]
    if granularity not in valid_granularities:
        raise BadRequestException(f"Invalid granularity. Must be one of: {', '.join(valid_granularities)}")
    
    # Calculate date range
    now = datetime.utcnow()
    if time_range == "7d":
        start_date = now - timedelta(days=7)
    elif time_range == "30d":
        start_date = now - timedelta(days=30)
    elif time_range == "90d":
        start_date = now - timedelta(days=90)
    elif time_range == "1y":
        start_date = now - timedelta(days=365)
    else:  # all
        start_date = None
    
    # Get listings
    query = select(MarketplaceListing).join(Asset).join(AssetCategory, isouter=True)
    if start_date:
        query = query.where(MarketplaceListing.created_at >= start_date)
    query = query.where(MarketplaceListing.status.in_([ListingStatus.ACTIVE, ListingStatus.SOLD]))
    
    if category:
        query = query.join(AssetCategory).where(AssetCategory.name == category)
    
    result = await db.execute(query)
    listings = result.scalars().all()
    
    # Group by date based on granularity
    trends = []
    values = []
    
    # Generate trend data points (simplified - in production, aggregate by date)
    current_date = start_date if start_date else datetime.utcnow() - timedelta(days=30)
    delta = timedelta(days=1) if granularity == "daily" else timedelta(weeks=1) if granularity == "weekly" else timedelta(days=30)
    
    while current_date <= now:
        # Count listings created up to this date
        count = sum(1 for l in listings if l.created_at <= current_date)
        value = float(count * 1000)  # Simplified metric
        values.append(value)
        
        trends.append(TrendDataPoint(
            date=current_date,
            value=value,
            category=category or "Overall"
        ))
        
        current_date += delta
    
    # Calculate summary
    if values:
        summary = {
            "min": min(values),
            "max": max(values),
            "average": sum(values) / len(values),
            "current": values[-1] if values else 0.0
        }
    else:
        summary = {"min": 0.0, "max": 0.0, "average": 0.0, "current": 0.0}
    
    return MarketTrendsResponse(
        trends=trends,
        time_range=time_range,
        granularity=granularity,
        summary=summary
    )


class MarketSummaryResponse(BaseModel):
    total_listings: int
    active_listings: int
    total_volume: Decimal
    average_price: Decimal
    total_offers: int
    completed_transactions: int
    market_sentiment: str
    top_categories: List[dict]
    updated_at: datetime


@public_router.get("/market-summary", response_model=MarketSummaryResponse)
async def get_market_summary(
    time_range: Optional[str] = Query("1d", description="Time range: 1d, 7d, 30d, 90d, 1y"),
    current_user: Optional[User] = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db)
):
    """Get overall market summary statistics"""
    from app.models.asset import Asset, AssetCategory
    
    # Validate time_range
    valid_ranges = ["1d", "7d", "30d", "90d", "1y"]
    if time_range not in valid_ranges:
        raise BadRequestException(f"Invalid time_range. Must be one of: {', '.join(valid_ranges)}")
    
    # Calculate date range
    now = datetime.utcnow()
    if time_range == "1d":
        start_date = now - timedelta(days=1)
    elif time_range == "7d":
        start_date = now - timedelta(days=7)
    elif time_range == "30d":
        start_date = now - timedelta(days=30)
    elif time_range == "90d":
        start_date = now - timedelta(days=90)
    else:  # 1y
        start_date = now - timedelta(days=365)
    
    # Get statistics
    total_listings_query = select(func.count(MarketplaceListing.id))
    if start_date:
        total_listings_query = total_listings_query.where(MarketplaceListing.created_at >= start_date)
    total_listings_result = await db.execute(total_listings_query)
    total_listings = total_listings_result.scalar() or 0
    
    active_listings_query = select(func.count(MarketplaceListing.id)).where(
        MarketplaceListing.status == ListingStatus.ACTIVE
    )
    if start_date:
        active_listings_query = active_listings_query.where(MarketplaceListing.created_at >= start_date)
    active_listings_result = await db.execute(active_listings_query)
    active_listings = active_listings_result.scalar() or 0
    
    # Total volume and average price
    volume_query = select(func.sum(MarketplaceListing.asking_price))
    if start_date:
        volume_query = volume_query.where(MarketplaceListing.created_at >= start_date)
    volume_result = await db.execute(volume_query)
    total_volume = volume_result.scalar() or Decimal(0)
    
    avg_price_query = select(func.avg(MarketplaceListing.asking_price))
    if start_date:
        avg_price_query = avg_price_query.where(MarketplaceListing.created_at >= start_date)
    avg_price_result = await db.execute(avg_price_query)
    average_price = avg_price_result.scalar() or Decimal(0)
    
    # Total offers
    offers_query = select(func.count(Offer.id))
    if start_date:
        offers_query = offers_query.where(Offer.created_at >= start_date)
    offers_result = await db.execute(offers_query)
    total_offers = offers_result.scalar() or 0
    
    # Completed transactions
    completed_query = select(func.count(MarketplaceListing.id)).where(
        MarketplaceListing.status == ListingStatus.SOLD
    )
    if start_date:
        completed_query = completed_query.where(MarketplaceListing.created_at >= start_date)
    completed_result = await db.execute(completed_query)
    completed_transactions = completed_result.scalar() or 0
    
    # Market sentiment (simplified - based on active vs sold ratio)
    if total_listings > 0:
        sold_ratio = completed_transactions / total_listings
        if sold_ratio > 0.3:
            market_sentiment = "bullish"
        elif sold_ratio < 0.1:
            market_sentiment = "bearish"
        else:
            market_sentiment = "neutral"
    else:
        market_sentiment = "neutral"
    
    # Top categories
    category_query = select(
        AssetCategory.name.label("category"),
        func.count(MarketplaceListing.id).label("count"),
        func.sum(MarketplaceListing.asking_price).label("total_value")
    ).join(
        Asset, Asset.category_id == AssetCategory.id
    ).join(
        MarketplaceListing, MarketplaceListing.asset_id == Asset.id
    )
    if start_date:
        category_query = category_query.where(MarketplaceListing.created_at >= start_date)
    category_query = category_query.group_by(AssetCategory.name).order_by(func.count(MarketplaceListing.id).desc()).limit(5)
    
    category_result = await db.execute(category_query)
    top_categories = [
        {
            "category": row.category,
            "count": row.count,
            "total_value": float(row.total_value or 0)
        }
        for row in category_result.all()
    ]
    
    return MarketSummaryResponse(
        total_listings=total_listings,
        active_listings=active_listings,
        total_volume=total_volume,
        average_price=average_price,
        total_offers=total_offers,
        completed_transactions=completed_transactions,
        market_sentiment=market_sentiment,
        top_categories=top_categories,
        updated_at=now
    )


# ==================== Watchlist Management APIs ====================

class WatchlistItemCreate(BaseModel):
    listing_id: UUID
    notes: Optional[str] = None


class WatchlistItemResponse(BaseModel):
    id: UUID
    listing_id: UUID
    listing_title: str
    listing_category: Optional[str]
    asking_price: Decimal
    currency: str
    listing_status: str
    asset_type: Optional[str]
    thumbnail_url: Optional[str]
    added_at: datetime
    price_change_since_added: Optional[Decimal] = None
    price_change_percentage: Optional[float] = None
    notes: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WatchlistItemUpdate(BaseModel):
    notes: Optional[str] = None


@router.get("/watchlist", response_model=List[WatchlistItemResponse])
async def get_watchlist(
    status_filter: Optional[str] = Query(None, description="Filter by listing status"),
    category: Optional[str] = Query(None),
    min_price: Optional[Decimal] = Query(None, ge=0),
    max_price: Optional[Decimal] = Query(None, ge=0),
    sort_by: Optional[str] = Query("added_at", description="Sort by: added_at, price, name"),
    sort_order: Optional[str] = Query(None, description="asc or desc. Defaults: price/name asc, added_at desc (newest first)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all items in the authenticated user's watchlist"""
    from app.api.deps import get_account
    from app.models.asset import Asset, AssetCategory

    account = await get_account(current_user=current_user, db=db)

    query = select(WatchlistItem).where(WatchlistItem.account_id == account.id)

    # Apply filters
    if status_filter:
        try:
            status_enum = ListingStatus(status_filter)
            query = query.where(WatchlistItem.listing_status == status_enum)
        except ValueError:
            raise BadRequestException(f"Invalid status_filter: {status_filter}")

    if category:
        query = query.where(WatchlistItem.listing_category == category)

    if min_price is not None:
        query = query.where(WatchlistItem.asking_price >= min_price)
    if max_price is not None:
        query = query.where(WatchlistItem.asking_price <= max_price)

    # Apply sorting. Without an explicit sort_order the historical defaults
    # hold (price/name ascending, added_at newest-first).
    sort_column = {
        "price": WatchlistItem.asking_price,
        "name": WatchlistItem.listing_title,
    }.get(sort_by, WatchlistItem.created_at)
    if sort_order is None:
        order_clause = sort_column.desc() if sort_by not in ("price", "name") else sort_column.asc()
    else:
        order = sort_order.strip().lower()
        if order == "asc":
            order_clause = sort_column.asc()
        elif order == "desc":
            order_clause = sort_column.desc()
        else:
            raise BadRequestException(
                f"Invalid sort_order '{sort_order}'. Must be 'asc' or 'desc'.",
                code="INVALID_SORT_ORDER",
            )
    query = query.order_by(order_clause)
    
    result = await db.execute(query)
    watchlist_items = result.scalars().all()
    
    # Calculate price changes and build response
    response_items = []
    for item in watchlist_items:
        price_change = item.asking_price - item.price_at_added
        price_change_pct = None
        if item.price_at_added > 0:
            price_change_pct = float((price_change / item.price_at_added) * 100)
        
        response_items.append(WatchlistItemResponse(
            id=item.id,
            listing_id=item.listing_id,
            listing_title=item.listing_title,
            listing_category=item.listing_category,
            asking_price=item.asking_price,
            currency=item.currency,
            listing_status=item.listing_status.value if hasattr(item.listing_status, 'value') else str(item.listing_status),
            asset_type=item.asset_type,
            thumbnail_url=item.thumbnail_url,
            added_at=item.created_at,
            price_change_since_added=price_change,
            price_change_percentage=price_change_pct,
            notes=item.notes,
            updated_at=item.updated_at
        ))
    
    return response_items


@router.post("/watchlist", response_model=WatchlistItemResponse, status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    watchlist_data: WatchlistItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Add a listing to the authenticated user's watchlist"""
    from app.api.deps import get_account
    from app.models.asset import Asset, AssetCategory, AssetPhoto
    
    account = await get_account(current_user=current_user, db=db)
    
    # Check if listing exists
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == watchlist_data.listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    
    if not listing:
        raise NotFoundException("Listing", str(watchlist_data.listing_id))
    
    # Check if already in watchlist
    existing_result = await db.execute(
        select(WatchlistItem).where(
            and_(
                WatchlistItem.account_id == account.id,
                WatchlistItem.listing_id == watchlist_data.listing_id
            )
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        raise BadRequestException("Listing already in watchlist")
    
    # Get asset details
    asset_result = await db.execute(
        select(Asset).where(Asset.id == listing.asset_id)
    )
    asset = asset_result.scalar_one_or_none()
    
    category_name = None
    asset_type = None
    if asset:
        asset_type = asset.asset_type.name if asset.asset_type else None
        if asset.category_id:
            category_result = await db.execute(
                select(AssetCategory).where(AssetCategory.id == asset.category_id)
            )
            category_obj = category_result.scalar_one_or_none()
            if category_obj:
                category_name = category_obj.name
    
    # Get thumbnail
    thumbnail_url = None
    if asset:
        photo_result = await db.execute(
            select(AssetPhoto).where(
                and_(
                    AssetPhoto.asset_id == asset.id,
                    AssetPhoto.is_primary == True
                )
            ).limit(1)
        )
        photo = photo_result.scalar_one_or_none()
        if photo:
            thumbnail_url = photo.thumbnail_url or photo.url
    
    # Create watchlist item
    watchlist_item = WatchlistItem(
        account_id=account.id,
        listing_id=watchlist_data.listing_id,
        listing_title=listing.title,
        listing_category=category_name,
        asking_price=listing.asking_price,
        currency=listing.currency,
        listing_status=listing.status,
        asset_type=asset_type,
        thumbnail_url=thumbnail_url,
        price_at_added=listing.asking_price,
        notes=watchlist_data.notes
    )
    
    db.add(watchlist_item)
    await db.commit()
    await db.refresh(watchlist_item)
    
    logger.info(f"Listing {watchlist_data.listing_id} added to watchlist for account {account.id}")
    
    return WatchlistItemResponse(
        id=watchlist_item.id,
        listing_id=watchlist_item.listing_id,
        listing_title=watchlist_item.listing_title,
        listing_category=watchlist_item.listing_category,
        asking_price=watchlist_item.asking_price,
        currency=watchlist_item.currency,
        listing_status=watchlist_item.listing_status.value if hasattr(watchlist_item.listing_status, 'value') else str(watchlist_item.listing_status),
        asset_type=watchlist_item.asset_type,
        thumbnail_url=watchlist_item.thumbnail_url,
        added_at=watchlist_item.created_at,
        notes=watchlist_item.notes
    )


@router.get("/watchlist/check/{listing_id}")
async def check_watchlist_status(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Check if a specific listing is in the authenticated user's watchlist"""
    from app.api.deps import get_account
    
    account = await get_account(current_user=current_user, db=db)
    
    # Verify listing exists
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    
    if not listing:
        raise NotFoundException("Listing", str(listing_id))
    
    # Check if in watchlist
    result = await db.execute(
        select(WatchlistItem).where(
            and_(
                WatchlistItem.account_id == account.id,
                WatchlistItem.listing_id == listing_id
            )
        )
    )
    watchlist_item = result.scalar_one_or_none()
    
    if watchlist_item:
        return {
            "is_in_watchlist": True,
            "watchlist_item_id": watchlist_item.id,
            "added_at": watchlist_item.created_at
        }
    else:
        return {
            "is_in_watchlist": False
        }


@router.delete("/watchlist/{watchlist_item_id}")
async def remove_from_watchlist(
    watchlist_item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove an item from the authenticated user's watchlist"""
    from app.api.deps import get_account
    
    account = await get_account(current_user=current_user, db=db)
    
    result = await db.execute(
        select(WatchlistItem).where(
            and_(
                WatchlistItem.id == watchlist_item_id,
                WatchlistItem.account_id == account.id
            )
        )
    )
    watchlist_item = result.scalar_one_or_none()
    
    if not watchlist_item:
        raise NotFoundException("Watchlist item", str(watchlist_item_id))
    
    await db.delete(watchlist_item)
    await db.commit()
    
    logger.info(f"Watchlist item {watchlist_item_id} removed for account {account.id}")
    return {"message": "Item removed from watchlist successfully"}


@router.put("/watchlist/{watchlist_item_id}", response_model=WatchlistItemResponse)
async def update_watchlist_item(
    watchlist_item_id: UUID,
    watchlist_data: WatchlistItemUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a watchlist item (e.g., notes)"""
    from app.api.deps import get_account
    
    account = await get_account(current_user=current_user, db=db)
    
    result = await db.execute(
        select(WatchlistItem).where(
            and_(
                WatchlistItem.id == watchlist_item_id,
                WatchlistItem.account_id == account.id
            )
        )
    )
    watchlist_item = result.scalar_one_or_none()
    
    if not watchlist_item:
        raise NotFoundException("Watchlist item", str(watchlist_item_id))
    
    # Update notes if provided
    if watchlist_data.notes is not None:
        watchlist_item.notes = watchlist_data.notes
    
    await db.commit()
    await db.refresh(watchlist_item)
    
    # Calculate price change
    price_change = watchlist_item.asking_price - watchlist_item.price_at_added
    price_change_pct = None
    if watchlist_item.price_at_added > 0:
        price_change_pct = float((price_change / watchlist_item.price_at_added) * 100)
    
    return WatchlistItemResponse(
        id=watchlist_item.id,
        listing_id=watchlist_item.listing_id,
        listing_title=watchlist_item.listing_title,
        listing_category=watchlist_item.listing_category,
        asking_price=watchlist_item.asking_price,
        currency=watchlist_item.currency,
        listing_status=watchlist_item.listing_status.value if hasattr(watchlist_item.listing_status, 'value') else str(watchlist_item.listing_status),
        asset_type=watchlist_item.asset_type,
        thumbnail_url=watchlist_item.thumbnail_url,
        added_at=watchlist_item.created_at,
        price_change_since_added=price_change,
        price_change_percentage=price_change_pct,
        notes=watchlist_item.notes,
        updated_at=watchlist_item.updated_at
    )
async def check_watchlist_status(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Check if a specific listing is in the authenticated user's watchlist"""
    from app.api.deps import get_account
    
    account = await get_account(current_user=current_user, db=db)
    
    # Verify listing exists
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    
    if not listing:
        raise NotFoundException("Listing", str(listing_id))
    
    # Check if in watchlist
    result = await db.execute(
        select(WatchlistItem).where(
            and_(
                WatchlistItem.account_id == account.id,
                WatchlistItem.listing_id == listing_id
            )
        )
    )
    watchlist_item = result.scalar_one_or_none()
    
    if watchlist_item:
        return {
            "is_in_watchlist": True,
            "watchlist_item_id": watchlist_item.id,
            "added_at": watchlist_item.created_at
        }
    else:
        return {
            "is_in_watchlist": False
        }

