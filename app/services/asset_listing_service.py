"""Auto-publish a concierge-valued asset to the marketplace.

When staff (admin/advisor) finish a concierge valuation, the asset is published
to the public marketplace with no investor "initiate sale" step. Publishing
requires BOTH conditions, in any order:

  1. the appraisal has a saved amount (``estimated_value``), and
  2. a staff-uploaded ``document_type == "valuation"`` document exists.

Additionally the asset must have a category (``category_id``) — the public
marketplace browse is category-driven, so uncategorized listings are never
auto-published (see ``asset_is_categorized``).

The created listing is owned by the asset's owner account, priced at the
valuation amount, and immediately public (``APPROVED``). Owner gates
(verification / subscription / KYB) are intentionally bypassed — this is a
staff-driven concierge publish. Re-running is idempotent: an existing open
listing for the asset is re-priced instead of duplicated.

`maybe_publish_valued_asset` is best-effort and never raises into its caller —
the valuation/document save has already been committed by the time it runs.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, and_

from app.models.asset import Asset, AssetAppraisal, AppraisalDocument
from app.models.marketplace import MarketplaceListing, ListingStatus
from app.utils.helpers import calculate_listing_fee
from app.utils.logger import logger

VALUATION_DOCUMENT_TYPE = "valuation"

# Frontend variants that all mean "this is the valuation report".
_VALUATION_ALIASES = {"valuation", "valuation report"}


def normalize_document_type(document_type: Optional[str]) -> Optional[str]:
    """Collapse valuation-report aliases ("Valuation Report", "valuation_report",
    …) to the canonical VALUATION_DOCUMENT_TYPE; other types pass through as-is.
    The auto-publish trigger matches on the canonical value, so a near-miss tag
    must not silently disable publishing."""
    if not document_type:
        return document_type
    normalized = " ".join(
        document_type.strip().lower().replace("-", " ").replace("_", " ").split()
    )
    if normalized in _VALUATION_ALIASES:
        return VALUATION_DOCUMENT_TYPE
    return document_type

# An existing listing in one of these states means the asset is already (or
# pending) on the marketplace — re-price it instead of creating a duplicate.
_OPEN_LISTING_STATUSES = [
    ListingStatus.PENDING_APPROVAL,
    ListingStatus.APPROVED,
    ListingStatus.ACTIVE,
]


def ready_to_publish(estimated_value: Optional[Decimal], has_valuation_document: bool) -> bool:
    """Both conditions must hold before an asset is auto-published."""
    return estimated_value is not None and bool(has_valuation_document)


def asset_is_categorized(asset) -> bool:
    """Only categorized assets may be auto-published — the marketplace browse
    UI is category-driven, so an uncategorized listing would be unreachable
    through every category tab/chip/filter."""
    return asset is not None and asset.category_id is not None


async def _has_valuation_document(db, appraisal_id) -> bool:
    # Normalize in Python so rows saved with an alias tag (e.g. "Valuation
    # Report") before write-side normalization existed still count.
    types = (await db.execute(
        select(AppraisalDocument.document_type).where(
            AppraisalDocument.appraisal_id == appraisal_id,
        )
    )).scalars().all()
    return any(normalize_document_type(t) == VALUATION_DOCUMENT_TYPE for t in types if t)


def listing_price_for_asset(current_value: Optional[Decimal], purchase_price: Optional[Decimal]) -> Optional[Decimal]:
    """Asking price for an auto-listed active asset: current value, falling back
    to purchase price. None when the asset has no usable (positive) price —
    a 0-priced public listing would be worse than no listing."""
    if current_value and current_value > 0:
        return current_value
    if purchase_price and purchase_price > 0:
        return purchase_price
    return None


async def ensure_listing_for_active_asset(db, asset: Asset, approved_by=None) -> Optional[MarketplaceListing]:
    """Ensure an ACTIVE asset has a public marketplace listing.

    Every asset with status 'active' ("Active Investment") is public in the
    marketplace. Idempotent: an existing open listing is left as-is. Assets
    without a usable price are skipped (logged). Best-effort — never raises
    into the caller, since asset create/update has already been committed.
    """
    try:
        status_value = asset.status.value if hasattr(asset.status, "value") else asset.status
        if status_value != "active":
            return None

        price = listing_price_for_asset(asset.current_value, asset.purchase_price)
        if price is None:
            logger.info(f"Auto-list: active asset {asset.id} has no usable price; not listing")
            return None

        if not asset_is_categorized(asset):
            logger.warning(f"Auto-list: active asset {asset.id} has no category; not listing")
            return None

        existing = (await db.execute(
            select(MarketplaceListing).where(and_(
                MarketplaceListing.asset_id == asset.id,
                MarketplaceListing.status.in_(_OPEN_LISTING_STATUSES),
            )).limit(1)
        )).scalar_one_or_none()
        if existing is not None:
            return existing

        now = datetime.now(timezone.utc)
        listing = MarketplaceListing(
            account_id=asset.account_id,
            asset_id=asset.id,
            title=asset.name or asset.asset_code or "Untitled Asset",
            description=asset.description,
            asking_price=price,
            currency=asset.currency or "USD",
            listing_fee=calculate_listing_fee(price),
            listing_fee_paid=False,
            status=ListingStatus.APPROVED,  # immediately public
            approved_by=approved_by,
            approved_at=now,
        )
        db.add(listing)
        await db.commit()
        await db.refresh(listing)
        logger.info(f"Auto-list: active asset {asset.id} listed as {listing.id} at {price}")
        return listing

    except Exception as e:
        await db.rollback()
        logger.error(f"Auto-list: failed to list active asset {asset.id}: {e}", exc_info=True)
        return None


async def maybe_publish_valued_asset(db, appraisal: AssetAppraisal, staff_user) -> Optional[MarketplaceListing]:
    """Publish (or re-price) the asset's marketplace listing when both the
    valuation amount and a valuation document are present. Never raises."""
    try:
        has_doc = await _has_valuation_document(db, appraisal.id)
        if not ready_to_publish(appraisal.estimated_value, has_doc):
            return None

        asset = (await db.execute(
            select(Asset).where(Asset.id == appraisal.asset_id)
        )).scalar_one_or_none()
        if asset is None:
            logger.warning(f"Auto-list: asset {appraisal.asset_id} not found for appraisal {appraisal.id}")
            return None

        if not asset_is_categorized(asset):
            logger.warning(
                f"Auto-list: asset {asset.id} has no category; not publishing "
                f"(appraisal {appraisal.id}). Set a category on the asset to publish."
            )
            return None

        price = appraisal.estimated_value
        currency = asset.currency or "USD"
        now = datetime.now(timezone.utc)

        # Idempotency: re-price an existing open listing rather than duplicate.
        existing = (await db.execute(
            select(MarketplaceListing).where(and_(
                MarketplaceListing.asset_id == asset.id,
                MarketplaceListing.status.in_(_OPEN_LISTING_STATUSES),
            )).limit(1)
        )).scalar_one_or_none()

        if existing is not None:
            existing.asking_price = price
            existing.currency = currency
            existing.listing_fee = calculate_listing_fee(price)
            existing.status = ListingStatus.APPROVED
            existing.approved_by = staff_user.id
            existing.approved_at = now
            existing.rejection_reason = None
            await db.commit()
            logger.info(f"Auto-list: re-priced listing {existing.id} for asset {asset.id} -> {price}")
            return existing

        listing = MarketplaceListing(
            account_id=asset.account_id,
            asset_id=asset.id,
            title=asset.name,
            description=asset.description,
            asking_price=price,
            currency=currency,
            listing_fee=calculate_listing_fee(price),   # 2%, settled at sale, not charged upfront
            listing_fee_paid=False,
            status=ListingStatus.APPROVED,               # immediately public
            approved_by=staff_user.id,
            approved_at=now,
        )
        db.add(listing)
        await db.commit()
        await db.refresh(listing)
        logger.info(f"Auto-list: published asset {asset.id} as listing {listing.id} at {price} {currency}")

        # Notify the owner (best-effort).
        try:
            from app.services.notification_service import NotificationService
            from app.models.notification import NotificationType
            await NotificationService.create_notification(
                db=db, account_id=asset.account_id,
                notification_type=NotificationType.LISTING_APPROVED,
                title="Your asset is live in the marketplace",
                message=f"'{asset.name}' has been valued and listed in the marketplace at {price} {currency}.",
                send_email=False,
            )
        except Exception as e:
            logger.error(f"Auto-list: failed to notify owner for asset {asset.id}: {e}")

        return listing

    except Exception as e:
        await db.rollback()
        logger.error(f"Auto-list: failed to publish asset for appraisal {appraisal.id}: {e}", exc_info=True)
        return None
