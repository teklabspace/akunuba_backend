"""Manual listing creation was removed (2026-08-18): the marketplace is now
appraisal-driven only, so the four listing-detail fields (expected_return,
duration, risk_level, slots_total) can no longer be set by a seller filling
out a create-listing form. Two things had to change to keep listings from
being published blank:

1. `PUT /concierge/appraisals/{id}/valuation` -- the staff endpoint that
   finalizes a valuation and triggers auto-publish -- now REQUIRES the four
   fields, and threads them into the listing it publishes/re-prices.
2. `PUT /marketplace/listings/{id}` now also accepts staff (admin, or an
   advisor for one of their assigned clients) editing a listing they don't
   own, scoped to descriptive fields only -- so the 8 pre-existing listings
   that already show N/A, and the asset_listing_service.py auto-publish
   paths that still don't collect details, have someone who can fix them.

Two other trigger paths can ALSO cause a first-time publish without ever
supplying `details` -- uploading the "valuation" document, and PATCH
.../status moving an appraisal straight to COMPLETED. Both are covered here
by confirming maybe_publish_valued_asset itself holds off on a blank
first-time publish, rather than trusting each call site to remember to pass
details.

Runs under pytest *or* standalone:  python tests/test_staff_listing_details.py
"""
import re
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.concierge import AppraisalValuationUpdate
from app.services.listing_details_policy import REQUIRED_DETAIL_FIELDS

COMPLETE_VALUATION = {
    "appraised_value": "250000.00",
    "valuation_date": "2026-08-18",
    "expected_return": "8.5%",
    "duration": "36 months",
    "risk_level": "medium",
    "slots_total": 40,
}


# --- the four fields are required to finalize a valuation ------------------

def test_a_complete_valuation_payload_validates():
    AppraisalValuationUpdate(**COMPLETE_VALUATION)


@pytest.mark.parametrize("field", REQUIRED_DETAIL_FIELDS)
def test_omitting_any_listing_detail_field_is_rejected(field):
    payload = {k: v for k, v in COMPLETE_VALUATION.items() if k != field}
    with pytest.raises(ValidationError):
        AppraisalValuationUpdate(**payload)


def test_an_invalid_risk_level_is_rejected():
    with pytest.raises(ValidationError):
        AppraisalValuationUpdate(**{**COMPLETE_VALUATION, "risk_level": "extreme"})


def test_zero_slots_is_a_valid_value():
    # Same convention as listing_details_policy._is_blank: 0 is a real value.
    AppraisalValuationUpdate(**{**COMPLETE_VALUATION, "slots_total": 0})


def test_an_unrecognized_field_is_rejected_not_silently_dropped():
    # The reported bug: a prior version of this model had no declared listing
    # fields, so the frontend's payload 200'd with them silently discarded.
    # extra="forbid" turns any future field-name mismatch into a loud 422
    # instead of a repeat of that failure mode.
    with pytest.raises(ValidationError):
        AppraisalValuationUpdate(**{**COMPLETE_VALUATION, "riskLevel": "medium"})


# --- route wiring: finalize-valuation threads details through --------------

def test_update_appraisal_valuation_passes_details_to_publish():
    import inspect

    from app.api.v1.concierge import update_appraisal_valuation

    source = inspect.getsource(update_appraisal_valuation)
    assert "maybe_publish_valued_asset(" in source
    assert "details=" in source
    for field in REQUIRED_DETAIL_FIELDS:
        assert f"valuation_data.{field}" in source, (
            f"finalize-valuation must forward {field} to the publish call"
        )


# --- asset_listing_service: no first-time publish without details ----------

def test_maybe_publish_valued_asset_guards_new_listings_on_missing_details():
    import inspect

    from app.services.asset_listing_service import maybe_publish_valued_asset

    source = inspect.getsource(maybe_publish_valued_asset)
    assert "missing_required_details(" in source, (
        "a first-time publish (no existing listing) must not go live without "
        "the four required fields, regardless of which trigger fired -- "
        "finalize-valuation, document upload, or PATCH .../status"
    )


def test_ensure_listing_for_active_asset_requires_details():
    import inspect

    from app.services.asset_listing_service import ensure_listing_for_active_asset

    source = inspect.getsource(ensure_listing_for_active_asset)
    assert "missing_required_details(" in source, (
        "this path has no details source today (see the no-caller test below) "
        "-- if it's ever wired up, it must not reproduce the N/A bug"
    )


def test_ensure_listing_for_active_asset_has_no_wired_caller():
    """Documents an intentional invariant: manual/self-service listing was
    removed, so this auto-publish path is currently unreachable from
    anywhere. If this test starts failing, someone added a caller -- confirm
    it actually supplies `details` (see the guard test above) before treating
    that as fine."""
    app_dir = ROOT / "app"
    callers = []
    for path in app_dir.rglob("*.py"):
        if path.name == "asset_listing_service.py":
            continue  # the definition itself
        text = path.read_text(encoding="utf-8")
        if re.search(r"ensure_listing_for_active_asset\(", text):
            callers.append(str(path.relative_to(ROOT)))
    assert callers == [], f"New caller(s) found: {callers} -- confirm they pass `details`"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
