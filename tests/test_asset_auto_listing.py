"""Tests for the concierge valuation -> marketplace auto-publish predicate.

Publishing requires BOTH the valuation amount AND a valuation document, in any
order. `ready_to_publish` is the pure gate both concierge endpoints funnel
through before creating/updating a listing.

Runs under pytest *or* standalone:  python tests/test_asset_auto_listing.py
"""
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace
from uuid import uuid4

from app.services.asset_listing_service import (
    ready_to_publish,
    normalize_document_type,
    listing_price_for_asset,
    asset_is_categorized,
    VALUATION_DOCUMENT_TYPE,
    _OPEN_LISTING_STATUSES,
)
from app.models.marketplace import ListingStatus


def test_publishes_only_when_both_present():
    assert ready_to_publish(Decimal("1000"), True) is True


def test_amount_without_valuation_doc_does_not_publish():
    assert ready_to_publish(Decimal("1000"), False) is False


def test_valuation_doc_without_amount_does_not_publish():
    assert ready_to_publish(None, True) is False


def test_neither_present_does_not_publish():
    assert ready_to_publish(None, False) is False


def test_zero_amount_still_counts_as_set():
    # A saved amount of 0 is still "set" — only None means no amount.
    assert ready_to_publish(Decimal("0"), True) is True


def test_valuation_document_type_constant():
    assert VALUATION_DOCUMENT_TYPE == "valuation"


def test_idempotency_status_set():
    # A duplicate is avoided when a listing already exists in any open state.
    assert set(_OPEN_LISTING_STATUSES) == {
        ListingStatus.PENDING_APPROVAL,
        ListingStatus.APPROVED,
        ListingStatus.ACTIVE,
    }
    # Terminal states must NOT block a fresh listing.
    assert ListingStatus.SOLD not in _OPEN_LISTING_STATUSES
    assert ListingStatus.REJECTED not in _OPEN_LISTING_STATUSES


def test_valuation_aliases_normalize():
    # Frontends have sent "Valuation Report" etc.; all aliases must count as
    # the valuation doc or the auto-publish trigger silently never fires.
    for alias in [
        "valuation", "Valuation", " VALUATION ",
        "Valuation Report", "valuation_report", "valuation-report", "VALUATION  REPORT",
    ]:
        assert normalize_document_type(alias) == VALUATION_DOCUMENT_TYPE, alias


def test_non_valuation_types_pass_through():
    assert normalize_document_type("insurance") == "insurance"
    assert normalize_document_type("Ownership Certificate") == "Ownership Certificate"
    assert normalize_document_type(None) is None
    assert normalize_document_type("") == ""


def test_listing_price_prefers_current_value():
    assert listing_price_for_asset(Decimal("100"), Decimal("50")) == Decimal("100")


def test_listing_price_falls_back_to_purchase_price():
    # current_value defaults to 0.00 on assets created without one.
    assert listing_price_for_asset(Decimal("0"), Decimal("50")) == Decimal("50")
    assert listing_price_for_asset(None, Decimal("50")) == Decimal("50")


def test_listing_price_none_when_asset_has_no_price():
    assert listing_price_for_asset(Decimal("0"), None) is None
    assert listing_price_for_asset(None, None) is None
    assert listing_price_for_asset(Decimal("0"), Decimal("0")) is None


def test_uncategorized_asset_is_not_auto_listed():
    # Marketplace browse is category-driven — an uncategorized listing would be
    # unreachable, so auto-publish must skip these assets.
    assert asset_is_categorized(None) is False
    assert asset_is_categorized(SimpleNamespace(category_id=None)) is False
    assert asset_is_categorized(SimpleNamespace(category_id=uuid4())) is True


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
