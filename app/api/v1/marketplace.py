from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from typing import List, Optional
from decimal import Decimal
from datetime import datetime, timedelta
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account, AccountType
from app.models.asset import Asset
from app.models.marketplace import (
    MarketplaceListing, Offer, EscrowTransaction,
    ListingStatus, OfferStatus, EscrowStatus
)
from app.core.exceptions import NotFoundException, BadRequestException, UnauthorizedException
from app.core.permissions import Role, Permission, has_permission
from app.utils.logger import logger
from app.utils.helpers import calculate_listing_fee, calculate_commission, generate_reference_id
from app.integrations.stripe_client import StripeClient
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


class ListingCreate(BaseModel):
    asset_id: UUID
    title: str
    description: Optional[str] = None
    asking_price: Decimal
    currency: str = "USD"


class ListingResponse(BaseModel):
    id: UUID
    title: str
    asking_price: Decimal
    currency: str
    status: str
    listing_fee: Optional[Decimal] = None
    created_at: datetime

    class Config:
        from_attributes = True


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
    
    # Check usage limit
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
    
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    
    logger.info(f"Listing created: {listing.id} by account {account.id}")
    return listing


@router.get("/listings", response_model=List[ListingResponse])
async def list_listings(
    status_filter: Optional[ListingStatus] = Query(None),
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all marketplace listings"""
    query = select(MarketplaceListing)
    
    if status_filter:
        query = query.where(MarketplaceListing.status == status_filter)
    else:
        query = query.where(MarketplaceListing.status.in_([
            ListingStatus.APPROVED, ListingStatus.ACTIVE
        ]))
    
    result = await db.execute(query)
    listings = result.scalars().all()
    
    return listings


@router.post("/listings/{listing_id}/approve", response_model=ListingResponse)
async def approve_listing(
    listing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Approve a listing (admin only)"""
    if not has_permission(current_user.role, Permission.APPROVE_LISTINGS):
        raise UnauthorizedException("Insufficient permissions")
    
    result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
    )
    listing = result.scalar_one_or_none()
    
    if not listing:
        raise NotFoundException("Listing", str(listing_id))
    
    listing.status = ListingStatus.APPROVED
    listing.approved_by = current_user.id
    listing.approved_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(listing)
    
    logger.info(f"Listing approved: {listing_id} by {current_user.id}")
    return listing


@router.post("/listings/{listing_id}/offers", status_code=status.HTTP_201_CREATED)
async def create_offer(
    listing_id: UUID,
    offer_data: OfferCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create an offer on a listing"""
    from app.api.deps import get_account, get_user_subscription_plan
    from app.core.features import Feature, has_feature, get_limit, check_usage_limit
    from sqlalchemy import func
    
    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)
    
    # Check subscription feature (FREE tier can make offers but limited)
    if not has_feature(plan, Feature.MARKETPLACE_OFFER):
        raise ForbiddenException("Making offers requires a subscription")
    
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
        raise ForbiddenException(f"Offer limit reached. Maximum {limit} active offers allowed for your plan.")
    
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    
    if not listing or listing.status != ListingStatus.ACTIVE:
        raise NotFoundException("Listing", str(listing_id))
    
    if listing.account_id == account.id:
        raise BadRequestException("Cannot make offer on your own listing")
    
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


class ListingUpdate(BaseModel):
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


@router.get("/listings/{listing_id}", response_model=ListingResponse)
async def get_listing(
    listing_id: UUID,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get listing details"""
    result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
    )
    listing = result.scalar_one_or_none()
    
    if not listing:
        raise NotFoundException("Listing", str(listing_id))
    
    return listing


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


@router.get("/offers/my", response_model=List[OfferResponse])
async def get_my_offers(
    status_filter: Optional[OfferStatus] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's offers"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    query = select(Offer).where(Offer.account_id == account.id)
    if status_filter:
        query = query.where(Offer.status == status_filter)
    
    result = await db.execute(query.order_by(Offer.created_at.desc()))
    offers = result.scalars().all()
    
    return offers


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


@router.get("/search")
async def search_listings(
    q: Optional[str] = Query(None, description="Search query"),
    asset_type: Optional[str] = Query(None),
    min_price: Optional[Decimal] = Query(None),
    max_price: Optional[Decimal] = Query(None),
    sort_by: Optional[str] = Query("created_at", description="Sort by: price, created_at"),
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Search marketplace listings"""
    query = select(MarketplaceListing).where(
        MarketplaceListing.status.in_([ListingStatus.APPROVED, ListingStatus.ACTIVE])
    )
    
    if q:
        query = query.where(
            or_(
                MarketplaceListing.title.ilike(f"%{q}%"),
                MarketplaceListing.description.ilike(f"%{q}%")
            )
        )
    
    if asset_type:
        # Join with Asset table
        from app.models.asset import Asset
        query = query.join(Asset).where(Asset.asset_type == asset_type)
    
    if min_price:
        query = query.where(MarketplaceListing.asking_price >= min_price)
    
    if max_price:
        query = query.where(MarketplaceListing.asking_price <= max_price)
    
    # Sorting
    if sort_by == "price":
        query = query.order_by(MarketplaceListing.asking_price.asc())
    else:
        query = query.order_by(MarketplaceListing.created_at.desc())
    
    result = await db.execute(query)
    listings = result.scalars().all()
    
    return listings

