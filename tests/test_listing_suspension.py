"""Tests for marketplace listing suspension during an open human appraisal.

Product rule: an asset must not be live/marketable on the public marketplace
while a human (non-API) appraisal is open on it. These tests cover the pure
decision helpers plus the public status-filter exclusion of `suspended`.

Runs under pytest *or* standalone:  python tests/test_listing_suspension.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.marketplace import _resolve_listing_status_filter, PUBLIC_LISTING_STATUSES
from app.core.exceptions import ForbiddenException
from app.models.asset import AppraisalStatus, AppraisalType
from app.models.marketplace import ListingStatus, OfferStatus
from app.services.asset_listing_service import (
    _OPEN_LISTING_STATUSES,
    OPEN_HUMAN_APPRAISAL_STATUSES,
    SUSPENSION_EXPIRABLE_OFFER_STATUSES,
    is_open_human_appraisal,
    restore_target_status,
    should_suspend_listing,
)


def test_suspended_enum_value():
    assert ListingStatus.SUSPENDED.value == "suspended"


def test_open_human_appraisal_statuses_match_creation_guard():
    # Must stay in lockstep with the one-open-appraisal guard in
    # POST /assets/{id}/appraisals and the frontend's "open" definition.
    assert set(OPEN_HUMAN_APPRAISAL_STATUSES) == {
        AppraisalStatus.PENDING,
        AppraisalStatus.IN_PROGRESS,
        AppraisalStatus.NEEDS_MORE_INFORMATION,
        AppraisalStatus.PROFESSIONAL_APPRAISAL_RECOMMENDED,
    }


def test_open_human_appraisal_predicate():
    for status in OPEN_HUMAN_APPRAISAL_STATUSES:
        assert is_open_human_appraisal(AppraisalType.CONCIERGE, status)
        assert is_open_human_appraisal(AppraisalType.COMPREHENSIVE, status)
        # AI/automated appraisals never suspend, whatever their status.
        assert not is_open_human_appraisal(AppraisalType.API, status)
    for terminal in (
        AppraisalStatus.COMPLETED,
        AppraisalStatus.CANCELLED,
        AppraisalStatus.AI_APPRAISED,
        AppraisalStatus.APPRAISAL_FAILED,
    ):
        assert not is_open_human_appraisal(AppraisalType.CONCIERGE, terminal)
    # Defensive: missing type/status never counts as open.
    assert not is_open_human_appraisal(None, AppraisalStatus.PENDING)
    assert not is_open_human_appraisal(AppraisalType.CONCIERGE, None)


def test_only_publicly_visible_listings_suspend():
    assert should_suspend_listing(ListingStatus.APPROVED)
    assert should_suspend_listing(ListingStatus.ACTIVE)
    for status in (
        ListingStatus.DRAFT,
        ListingStatus.PENDING_APPROVAL,
        ListingStatus.REJECTED,
        ListingStatus.SUSPENDED,
        ListingStatus.SOLD,
        ListingStatus.CANCELLED,
    ):
        assert not should_suspend_listing(status)


def test_restore_target_honors_pre_suspension_status():
    assert restore_target_status(ListingStatus.APPROVED) == ListingStatus.APPROVED
    assert restore_target_status(ListingStatus.ACTIVE) == ListingStatus.ACTIVE
    # Legacy/unknown pre-status falls back to APPROVED (public, not yet activated).
    assert restore_target_status(None) == ListingStatus.APPROVED


def test_expirable_offer_statuses():
    assert set(SUSPENSION_EXPIRABLE_OFFER_STATUSES) == {
        OfferStatus.PENDING,
        OfferStatus.COUNTERED,
    }


def test_suspended_listing_is_repriced_not_duplicated_on_publish():
    # maybe_publish_valued_asset matches "open" listings; a suspended listing
    # must be found and re-published, not shadowed by a duplicate row.
    assert ListingStatus.SUSPENDED in _OPEN_LISTING_STATUSES


def test_suspended_is_not_public():
    assert ListingStatus.SUSPENDED not in PUBLIC_LISTING_STATUSES
    try:
        _resolve_listing_status_filter(ListingStatus.SUSPENDED, is_staff=False)
        raise AssertionError("expected ForbiddenException for guest requesting suspended")
    except ForbiddenException:
        pass
    assert _resolve_listing_status_filter(ListingStatus.SUSPENDED, is_staff=True) == [
        ListingStatus.SUSPENDED
    ]


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
