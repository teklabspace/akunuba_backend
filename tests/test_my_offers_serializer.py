"""Tests for the GET /marketplace/offers/my item serializer.

Pure-helper tests (no DB): exercise _my_offer_item with stub ORM objects,
covering buyer vs seller role resolution, counterparty selection, escrow id
passthrough, and NULL-safe display names.
"""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.v1.marketplace import _my_offer_item  # noqa: E402
from app.models.asset import AssetType  # noqa: E402
from app.models.marketplace import OfferStatus  # noqa: E402


def _user(user_id, first="Jane", last="Doe", email="jane@example.com"):
    return SimpleNamespace(id=user_id, first_name=first, last_name=last, email=email)


def _account(account_id, user):
    return SimpleNamespace(id=account_id, user_id=user.id, user=user)


def _stub_offer(buyer_account, seller_account, **overrides):
    photo = SimpleNamespace(url="https://img/full.jpg", thumbnail_url="https://img/thumb.jpg")
    asset = SimpleNamespace(asset_type=AssetType.REAL_ESTATE, photos=[photo])
    listing = SimpleNamespace(
        id=uuid.uuid4(),
        account_id=seller_account.id,
        account=seller_account,
        asset=asset,
        title="Beach House",
    )
    offer = SimpleNamespace(
        id=uuid.uuid4(),
        listing_id=listing.id,
        listing=listing,
        account_id=buyer_account.id,
        account=buyer_account,
        offer_amount=12500,
        currency="USD",
        status=OfferStatus.PENDING,
        message="hi",
        created_at="2026-07-01T00:00:00Z",
        updated_at=None,
    )
    for key, value in overrides.items():
        setattr(offer, key, value)
    return offer


def test_buyer_role_and_counterparty():
    buyer_user, seller_user = _user(uuid.uuid4()), _user(uuid.uuid4(), "Sam", "Seller")
    buyer, seller = _account(uuid.uuid4(), buyer_user), _account(uuid.uuid4(), seller_user)
    offer = _stub_offer(buyer, seller)

    item = _my_offer_item(offer, viewer_account_id=buyer.id, escrow_id=None)

    assert item["role"] == "buyer"
    assert item["counterparty"] == "Sam Seller"
    assert item["counterparty_id"] == seller_user.id
    assert item["listing_title"] == "Beach House"
    assert item["asset_type"] == "real_estate"
    assert item["asset_thumbnail"] == "https://img/thumb.jpg"
    assert item["status"] == "pending"
    assert item["escrow_id"] is None
    assert item["updated_at"] == item["created_at"]  # NULL updated_at falls back


def test_seller_role_counterparty_and_escrow():
    buyer_user, seller_user = _user(uuid.uuid4(), "Bob", "Buyer"), _user(uuid.uuid4())
    buyer, seller = _account(uuid.uuid4(), buyer_user), _account(uuid.uuid4(), seller_user)
    escrow_id = uuid.uuid4()
    offer = _stub_offer(buyer, seller, status=OfferStatus.ACCEPTED)

    item = _my_offer_item(offer, viewer_account_id=seller.id, escrow_id=escrow_id)

    assert item["role"] == "seller"
    assert item["counterparty"] == "Bob Buyer"
    assert item["counterparty_id"] == buyer_user.id
    assert item["status"] == "accepted"
    assert item["escrow_id"] == escrow_id


def test_display_name_falls_back_to_email_then_unknown():
    buyer_user = _user(uuid.uuid4(), first=None, last=None, email="anon@x.com")
    seller_user = _user(uuid.uuid4(), first=None, last=None, email=None)
    buyer, seller = _account(uuid.uuid4(), buyer_user), _account(uuid.uuid4(), seller_user)
    offer = _stub_offer(buyer, seller)

    as_buyer = _my_offer_item(offer, viewer_account_id=buyer.id, escrow_id=None)
    assert as_buyer["counterparty"] == "Unknown"  # seller has no name and no email

    as_seller = _my_offer_item(offer, viewer_account_id=seller.id, escrow_id=None)
    assert as_seller["counterparty"] == "anon@x.com"


def test_missing_asset_and_photos_are_null_safe():
    buyer_user, seller_user = _user(uuid.uuid4()), _user(uuid.uuid4())
    buyer, seller = _account(uuid.uuid4(), buyer_user), _account(uuid.uuid4(), seller_user)
    offer = _stub_offer(buyer, seller)
    offer.listing.asset = None

    item = _my_offer_item(offer, viewer_account_id=buyer.id, escrow_id=None)

    assert item["asset_type"] is None
    assert item["asset_thumbnail"] is None


if __name__ == "__main__":
    test_buyer_role_and_counterparty()
    test_seller_role_counterparty_and_escrow()
    test_display_name_falls_back_to_email_then_unknown()
    test_missing_asset_and_photos_are_null_safe()
    print("All tests passed")
