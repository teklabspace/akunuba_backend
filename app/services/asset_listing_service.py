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

Suspension rule: while a HUMAN appraisal (any type except "API") is open on an
asset, the asset must not be live on the public marketplace. Opening one moves
an APPROVED/ACTIVE listing to SUSPENDED (open offers expire); the appraisal
reaching a terminal state either re-publishes at the new value (completed, via
the publish pair above) or restores the prior status/price (cancelled/failed).
Suspend/restore helpers share the best-effort never-raise contract.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, and_, update as sa_update

from app.models.asset import Asset, AssetAppraisal, AppraisalDocument, AppraisalStatus, AppraisalType
from app.models.marketplace import MarketplaceListing, ListingStatus, Offer, OfferStatus, WatchlistItem
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
# SUSPENDED is included so publishing after an appraisal re-prices/restores the
# suspended row rather than shadowing it with a new one.
_OPEN_LISTING_STATUSES = [
    ListingStatus.PENDING_APPROVAL,
    ListingStatus.APPROVED,
    ListingStatus.ACTIVE,
    ListingStatus.SUSPENDED,
]

# A human appraisal in one of these states blocks the asset from being live on
# the public marketplace. Kept in lockstep with the one-open-appraisal guard in
# POST /assets/{id}/appraisals (and the frontend's "open appraisal" definition).
OPEN_HUMAN_APPRAISAL_STATUSES = (
    AppraisalStatus.PENDING,
    AppraisalStatus.IN_PROGRESS,
    AppraisalStatus.NEEDS_MORE_INFORMATION,
    AppraisalStatus.PROFESSIONAL_APPRAISAL_RECOMMENDED,
)

# Only publicly visible listings get suspended; a pending_approval/draft listing
# is not public and simply cannot be approved while the appraisal is open.
SUSPENDABLE_LISTING_STATUSES = (ListingStatus.APPROVED, ListingStatus.ACTIVE)

# Offers still open when a listing suspends. They expire (price is about to be
# re-validated) rather than freeze; buyers re-offer against the new price.
SUSPENSION_EXPIRABLE_OFFER_STATUSES = (OfferStatus.PENDING, OfferStatus.COUNTERED)


def is_open_human_appraisal(appraisal_type, status) -> bool:
    """True when this (type, status) pair blocks marketplace visibility.
    AI/automated appraisals ("API") never do, whatever their status."""
    if appraisal_type is None or status is None:
        return False
    if appraisal_type == AppraisalType.API:
        return False
    return status in OPEN_HUMAN_APPRAISAL_STATUSES


def should_suspend_listing(listing_status) -> bool:
    return listing_status in SUSPENDABLE_LISTING_STATUSES


def restore_target_status(pre_suspension_status) -> ListingStatus:
    """Status a suspended listing returns to when the appraisal ends without a
    new valuation. Unknown/legacy bookkeeping falls back to APPROVED (public,
    not yet owner-activated)."""
    if pre_suspension_status in SUSPENDABLE_LISTING_STATUSES:
        return pre_suspension_status
    return ListingStatus.APPROVED


async def has_open_human_appraisal(db, asset_id, exclude_appraisal_id=None) -> bool:
    """Any open human appraisal on the asset (optionally ignoring one row —
    e.g. the appraisal whose own transition is being processed)."""
    conditions = [
        AssetAppraisal.asset_id == asset_id,
        AssetAppraisal.appraisal_type != AppraisalType.API,
        AssetAppraisal.status.in_(OPEN_HUMAN_APPRAISAL_STATUSES),
    ]
    if exclude_appraisal_id is not None:
        conditions.append(AssetAppraisal.id != exclude_appraisal_id)
    row = (await db.execute(
        select(AssetAppraisal.id).where(and_(*conditions)).limit(1)
    )).scalar_one_or_none()
    return row is not None


async def _sync_watchlist_rows(db, listing, price=None) -> None:
    """Keep denormalized watchlist copies of status (and price, on re-price)
    in step with the listing. Caller owns the commit."""
    values = {"listing_status": listing.status}
    if price is not None:
        values["asking_price"] = price
    await db.execute(
        sa_update(WatchlistItem)
        .where(WatchlistItem.listing_id == listing.id)
        .values(**values)
    )


async def _notify(db, account_id, title, message) -> None:
    """Best-effort bell notification; never raises."""
    try:
        from app.services.notification_service import NotificationService
        from app.models.notification import NotificationType
        await NotificationService.create_notification(
            db=db, account_id=account_id,
            notification_type=NotificationType.GENERAL,
            title=title, message=message, send_email=False,
        )
    except Exception as e:
        logger.error(f"Listing suspension: failed to notify account {account_id}: {e}")


async def suspend_listing_for_open_appraisal(db, asset_id, appraisal) -> Optional[MarketplaceListing]:
    """Pull the asset's live listing from the public marketplace because a human
    appraisal opened. Expires open offers and notifies owner + buyers.
    Best-effort — never raises; the appraisal write is already committed."""
    try:
        if not is_open_human_appraisal(appraisal.appraisal_type, appraisal.status):
            return None

        listing = (await db.execute(
            select(MarketplaceListing).where(and_(
                MarketplaceListing.asset_id == asset_id,
                MarketplaceListing.status.in_(SUSPENDABLE_LISTING_STATUSES),
            )).limit(1)
        )).scalar_one_or_none()
        if listing is None:
            return None

        listing.pre_suspension_status = listing.status
        listing.status = ListingStatus.SUSPENDED
        listing.suspended_at = datetime.now(timezone.utc)

        open_offers = (await db.execute(
            select(Offer).where(and_(
                Offer.listing_id == listing.id,
                Offer.status.in_(SUSPENSION_EXPIRABLE_OFFER_STATUSES),
            ))
        )).scalars().all()
        buyer_account_ids = []
        for offer in open_offers:
            offer.status = OfferStatus.EXPIRED
            if offer.account_id not in buyer_account_ids:
                buyer_account_ids.append(offer.account_id)

        await _sync_watchlist_rows(db, listing)
        await db.commit()
        logger.info(
            f"Suspended listing {listing.id} (was {listing.pre_suspension_status.value}) for asset "
            f"{asset_id}: appraisal {appraisal.id} opened; expired {len(open_offers)} offer(s)"
        )

        await _notify(
            db, listing.account_id,
            "Listing temporarily suspended",
            f"'{listing.title}' is hidden from the marketplace while an appraisal is in "
            f"progress. It will return automatically when the appraisal is finished.",
        )
        for buyer_account_id in buyer_account_ids:
            await _notify(
                db, buyer_account_id,
                "Offer expired",
                f"Your offer on '{listing.title}' expired because the listing entered a "
                f"valuation. You can make a new offer once it returns to the marketplace.",
            )
        return listing

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to suspend listing for asset {asset_id}: {e}", exc_info=True)
        return None


async def restore_listing_after_appraisal(db, asset_id, appraisal) -> Optional[MarketplaceListing]:
    """Return a suspended listing to its prior status at its ORIGINAL price —
    the cancelled/failed-appraisal path (no new valuation to apply). Completed
    appraisals restore through maybe_publish_valued_asset instead, which
    re-prices. No-op while another human appraisal is still open."""
    try:
        if await has_open_human_appraisal(db, asset_id, exclude_appraisal_id=appraisal.id):
            return None

        listing = (await db.execute(
            select(MarketplaceListing).where(and_(
                MarketplaceListing.asset_id == asset_id,
                MarketplaceListing.status == ListingStatus.SUSPENDED,
            )).limit(1)
        )).scalar_one_or_none()
        if listing is None:
            return None

        listing.status = restore_target_status(listing.pre_suspension_status)
        listing.pre_suspension_status = None
        listing.suspended_at = None

        await _sync_watchlist_rows(db, listing)
        await db.commit()
        logger.info(
            f"Restored listing {listing.id} to {listing.status.value} for asset {asset_id}: "
            f"appraisal {appraisal.id} ended as {appraisal.status.value if appraisal.status else None}"
        )

        await _notify(
            db, listing.account_id,
            "Listing restored to the marketplace",
            f"The appraisal on '{listing.title}' was closed without a new valuation, so "
            f"your listing is visible in the marketplace again at its previous price.",
        )
        return listing

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to restore listing for asset {asset_id}: {e}", exc_info=True)
        return None


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

        # Product rule: nothing goes live while a human appraisal is open.
        if await has_open_human_appraisal(db, asset.id):
            logger.info(f"Auto-list: asset {asset.id} has an open human appraisal; not listing")
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

        # Any open human appraisal (this one re-opened, or another) keeps the
        # asset off the public marketplace — publishing waits for it to end. In
        # every legitimate publish moment the triggering appraisal is already
        # committed as COMPLETED, so it never blocks itself here.
        if await has_open_human_appraisal(db, asset.id):
            logger.info(
                f"Auto-list: asset {asset.id} still has an open human appraisal; "
                f"not publishing (appraisal {appraisal.id})"
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
            was_suspended = existing.status == ListingStatus.SUSPENDED
            existing.asking_price = price
            existing.currency = currency
            existing.listing_fee = calculate_listing_fee(price)
            existing.status = ListingStatus.APPROVED
            existing.approved_by = staff_user.id
            existing.approved_at = now
            existing.rejection_reason = None
            existing.pre_suspension_status = None
            existing.suspended_at = None
            await _sync_watchlist_rows(db, existing, price=price)
            await db.commit()
            logger.info(f"Auto-list: re-priced listing {existing.id} for asset {asset.id} -> {price}")
            if was_suspended:
                await _notify(
                    db, existing.account_id,
                    "Your listing is back in the marketplace",
                    f"The appraisal on '{existing.title}' is complete. Your listing has been "
                    f"re-published at the appraised value of {price} {currency}.",
                )
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
