"""Tests for the public marketplace listing status-filter guard.

GET /marketplace/listings is public (optional auth). Its status_filter must never
let a guest/non-staff caller enumerate non-public listings (pending_approval,
rejected, draft, ...). Staff (APPROVE_LISTINGS) may filter to any status.

Runs under pytest *or* standalone:  python tests/test_listing_status_filter.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.marketplace import _resolve_listing_status_filter, PUBLIC_LISTING_STATUSES
from app.models.marketplace import ListingStatus
from app.core.exceptions import ForbiddenException


def test_no_filter_returns_public_statuses():
    assert _resolve_listing_status_filter(None, is_staff=False) == PUBLIC_LISTING_STATUSES
    assert _resolve_listing_status_filter(None, is_staff=True) == PUBLIC_LISTING_STATUSES


def test_public_status_allowed_for_guest():
    assert _resolve_listing_status_filter(ListingStatus.ACTIVE, is_staff=False) == [ListingStatus.ACTIVE]
    assert _resolve_listing_status_filter(ListingStatus.APPROVED, is_staff=False) == [ListingStatus.APPROVED]


def test_pending_approval_blocked_for_guest():
    # The exact exposure the frontend flagged.
    try:
        _resolve_listing_status_filter(ListingStatus.PENDING_APPROVAL, is_staff=False)
        raise AssertionError("expected ForbiddenException for guest requesting pending_approval")
    except ForbiddenException:
        pass


def test_rejected_blocked_for_guest():
    try:
        _resolve_listing_status_filter(ListingStatus.REJECTED, is_staff=False)
        raise AssertionError("expected ForbiddenException for guest requesting rejected")
    except ForbiddenException:
        pass


def test_staff_may_filter_any_status():
    assert _resolve_listing_status_filter(ListingStatus.PENDING_APPROVAL, is_staff=True) == [ListingStatus.PENDING_APPROVAL]
    assert _resolve_listing_status_filter(ListingStatus.REJECTED, is_staff=True) == [ListingStatus.REJECTED]


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
