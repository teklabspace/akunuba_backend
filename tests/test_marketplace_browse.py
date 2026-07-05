"""Tests for the public marketplace browse plumbing added for the home page:

- ListingResponse now carries category_group + primary photo URLs
  (thumbnail_url for cards, image_url for detail pages).
- /search accepts category_group (two-level browse taxonomy) and sort_order.
- Listings must have a categorized asset before approval/auto-publish.

Runs under pytest *or* standalone:  python tests/test_marketplace_browse.py
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.marketplace import (
    _listing_sort_clause,
    _resolve_category_group,
    _primary_photo,
    _listing_with_category,
    _require_categorized_asset,
)
from app.models.asset import CategoryGroup
from app.core.exceptions import BadRequestException


# ---------------------------------------------------------------- sort_order

def test_price_sort_defaults_ascending():
    assert str(_listing_sort_clause("price", None)).endswith("asking_price ASC")


def test_created_at_sort_defaults_descending():
    # No sort_order must preserve the historical newest-first default.
    assert str(_listing_sort_clause("created_at", None)).endswith("created_at DESC")
    assert str(_listing_sort_clause(None, None)).endswith("created_at DESC")


def test_explicit_sort_order_overrides_default():
    assert str(_listing_sort_clause("price", "desc")).endswith("asking_price DESC")
    assert str(_listing_sort_clause("price", "ASC ")).endswith("asking_price ASC")
    assert str(_listing_sort_clause("created_at", "asc")).endswith("created_at ASC")


def test_invalid_sort_order_rejected():
    try:
        _listing_sort_clause("price", "sideways")
        raise AssertionError("expected BadRequestException for invalid sort_order")
    except BadRequestException as e:
        assert e.code == "INVALID_SORT_ORDER"


# ------------------------------------------------------------ category_group

def test_category_group_matches_case_insensitively():
    assert _resolve_category_group("Assets") is CategoryGroup.ASSETS
    assert _resolve_category_group("assets") is CategoryGroup.ASSETS
    assert _resolve_category_group("  shadow wealth ") is CategoryGroup.SHADOW_WEALTH


def test_invalid_category_group_rejected():
    try:
        _resolve_category_group("Luxury")
        raise AssertionError("expected BadRequestException for unknown category_group")
    except BadRequestException as e:
        assert e.code == "INVALID_CATEGORY_GROUP"


# ------------------------------------------------------------- serialization

def _fake_listing(asset=None):
    return SimpleNamespace(
        id=uuid4(),
        asset_id=uuid4(),
        title="Ocean Pearl",
        asking_price=Decimal("345.00"),
        currency="USD",
        status="approved",
        listing_fee=Decimal("6.90"),
        rejection_reason=None,
        created_at=datetime.now(timezone.utc),
        asset=asset,
    )


def _fake_photo(url, thumbnail_url=None, is_primary=False):
    return SimpleNamespace(url=url, thumbnail_url=thumbnail_url, is_primary=is_primary)


def test_primary_photo_is_first_or_none():
    # Asset.photos is relationship-ordered is_primary-first; helper takes photos[0].
    primary = _fake_photo("p.jpg", is_primary=True)
    assert _primary_photo([primary, _fake_photo("other.jpg")]) is primary
    assert _primary_photo([]) is None
    assert _primary_photo(None) is None


def test_serializes_category_group_and_photo_urls():
    asset = SimpleNamespace(
        category=SimpleNamespace(name="Yachts", category_group=CategoryGroup.ASSETS),
        photos=[_fake_photo("full.jpg", thumbnail_url="thumb.jpg", is_primary=True)],
    )
    resp = _listing_with_category(_fake_listing(asset))
    assert resp.category == "Yachts"
    assert resp.category_group == "Assets"
    assert resp.image_url == "full.jpg"
    assert resp.thumbnail_url == "thumb.jpg"


def test_thumbnail_falls_back_to_full_image():
    asset = SimpleNamespace(
        category=None,
        photos=[_fake_photo("full.jpg", thumbnail_url=None)],
    )
    resp = _listing_with_category(_fake_listing(asset))
    assert resp.thumbnail_url == "full.jpg"
    assert resp.image_url == "full.jpg"


def test_serializes_without_asset_category_or_photos():
    resp = _listing_with_category(_fake_listing(asset=None))
    assert resp.category is None and resp.category_group is None
    assert resp.image_url is None and resp.thumbnail_url is None

    resp = _listing_with_category(_fake_listing(SimpleNamespace(category=None, photos=[])))
    assert resp.category is None and resp.image_url is None


# ------------------------------------------------------- category-required gate

def test_uncategorized_asset_blocks_approval():
    for asset in (None, SimpleNamespace(category_id=None)):
        try:
            _require_categorized_asset(asset)
            raise AssertionError("expected BadRequestException for uncategorized asset")
        except BadRequestException as e:
            assert e.code == "LISTING_CATEGORY_REQUIRED"


def test_categorized_asset_passes_gate():
    _require_categorized_asset(SimpleNamespace(category_id=uuid4()))


def _run_standalone():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_standalone() else 0)
