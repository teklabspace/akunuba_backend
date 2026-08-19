"""Pure tests for app/services/listing_details_policy.py.

Two reported-N/A causes on the marketplace listing detail page:

* Expected Returns / Duration / Risk Level / Slots were optional on create, so
  sellers submitted listings without them. 11 of 12 live listings had them
  empty and the detail page correctly rendered "N/A".
* PUT /marketplace/listings/{id} refused any listing past pending_approval, so
  those same sellers could never go back and fill them in — the values were
  frozen at approval and every live listing was stuck at N/A permanently.

The rule now: deal TERMS (title, description, asking_price) lock at approval
because open offers and escrow are priced against them; DESCRIPTIVE fields stay
editable while the listing is live.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.marketplace import ListingStatus
from app.services.listing_details_policy import (
    DETAILS_KEY,
    REQUIRED_DETAIL_FIELDS,
    TERMS_FIELDS,
    ListingNotEditable,
    ListingTermsLocked,
    ListingTermsOwnerOnly,
    ensure_staff_edit_scope,
    ensure_update_allowed,
    merge_details,
    missing_required_details,
)

COMPLETE = {
    "expected_return": "7.2%",
    "duration": "24 months",
    "risk_level": "medium",
    "slots_total": 50,
}


# --- what a listing must carry at creation --------------------------------

def test_the_four_reported_fields_are_the_required_set():
    assert REQUIRED_DETAIL_FIELDS == (
        "expected_return",
        "duration",
        "risk_level",
        "slots_total",
    )


def test_a_complete_payload_is_missing_nothing():
    assert missing_required_details(COMPLETE) == []


def test_an_absent_field_is_missing():
    payload = {k: v for k, v in COMPLETE.items() if k != "duration"}
    assert missing_required_details(payload) == ["duration"]


def test_an_explicit_null_is_missing():
    assert missing_required_details({**COMPLETE, "risk_level": None}) == ["risk_level"]


def test_a_blank_string_is_missing():
    # The create form sends "" for an untouched text input.
    assert missing_required_details({**COMPLETE, "expected_return": "   "}) == [
        "expected_return"
    ]


def test_missing_fields_are_reported_in_a_stable_order():
    assert missing_required_details({}) == list(REQUIRED_DETAIL_FIELDS)


def test_unrelated_fields_are_ignored():
    assert missing_required_details({**COMPLETE, "faqs": [], "title": "x"}) == []


def test_zero_slots_counts_as_supplied():
    # Deliberate: emptiness is None/blank only. Range checks are a separate
    # concern, not a "you forgot to fill this in" error.
    assert missing_required_details({**COMPLETE, "slots_total": 0}) == []


# --- who may edit what, and when ------------------------------------------

def test_draft_allows_editing_deal_terms():
    ensure_update_allowed(ListingStatus.DRAFT, ["title", "asking_price"])


def test_pending_approval_allows_editing_deal_terms():
    ensure_update_allowed(ListingStatus.PENDING_APPROVAL, ["asking_price"])


def test_approved_allows_descriptive_edits():
    # The whole point of the fix: filling in the four fields after approval.
    ensure_update_allowed(ListingStatus.APPROVED, list(REQUIRED_DETAIL_FIELDS))


def test_active_allows_descriptive_edits():
    ensure_update_allowed(ListingStatus.ACTIVE, ["overview", "faqs", "document_ids"])


def test_suspended_allows_descriptive_edits():
    # Suspended is a live listing temporarily pulled during an appraisal; it
    # gets restored, so stranding it at N/A would recreate the original bug.
    ensure_update_allowed(ListingStatus.SUSPENDED, ["expected_return"])


@pytest.mark.parametrize("field", TERMS_FIELDS)
def test_deal_terms_are_locked_once_approved(field):
    with pytest.raises(ListingTermsLocked):
        ensure_update_allowed(ListingStatus.APPROVED, [field])


def test_a_mixed_request_is_rejected_rather_than_partially_applied():
    with pytest.raises(ListingTermsLocked):
        ensure_update_allowed(ListingStatus.ACTIVE, ["expected_return", "asking_price"])


@pytest.mark.parametrize(
    "status", [ListingStatus.SOLD, ListingStatus.CANCELLED, ListingStatus.REJECTED]
)
def test_finished_listings_are_not_editable_at_all(status):
    with pytest.raises(ListingNotEditable):
        ensure_update_allowed(status, ["expected_return"])


def test_status_may_be_a_plain_string():
    # Callers hold ORM enums; tests and payloads hold strings.
    ensure_update_allowed("approved", ["duration"])
    with pytest.raises(ListingNotEditable):
        ensure_update_allowed("sold", ["duration"])


def test_an_empty_update_is_allowed_on_a_live_listing():
    ensure_update_allowed(ListingStatus.APPROVED, [])


# --- error codes the frontend switches on ---------------------------------

def test_error_codes_are_the_documented_strings():
    assert ListingTermsLocked().code == "LISTING_TERMS_LOCKED"
    assert ListingNotEditable().code == "LISTING_NOT_EDITABLE"
    assert ListingTermsOwnerOnly().code == "LISTING_TERMS_OWNER_ONLY"


# --- merging detail fields into meta_data ----------------------------------
# Shared by marketplace.py (seller/staff PUT) and asset_listing_service.py
# (auto-publish at finalize-valuation).

def test_merge_details_into_empty_meta_data():
    meta = merge_details(None, COMPLETE)
    assert meta[DETAILS_KEY] == COMPLETE


def test_merge_details_preserves_unrelated_meta_data_keys():
    existing = {"public_document_ids": ["doc-1"], DETAILS_KEY: {"expected_return": "5%"}}
    meta = merge_details(existing, {"duration": "12 months"})
    assert meta["public_document_ids"] == ["doc-1"]
    assert meta[DETAILS_KEY] == {"expected_return": "5%", "duration": "12 months"}


def test_merge_details_only_touches_provided_keys():
    existing = {DETAILS_KEY: dict(COMPLETE)}
    meta = merge_details(existing, {"duration": "36 months"})
    assert meta[DETAILS_KEY] == {**COMPLETE, "duration": "36 months"}


def test_merge_details_explicit_none_clears_a_key():
    existing = {DETAILS_KEY: dict(COMPLETE)}
    meta = merge_details(existing, {"risk_level": None})
    assert "risk_level" not in meta[DETAILS_KEY]
    assert meta[DETAILS_KEY]["expected_return"] == COMPLETE["expected_return"]


def test_merge_details_does_not_mutate_the_input_dict():
    existing = {DETAILS_KEY: {"expected_return": "5%"}}
    merge_details(existing, {"duration": "12 months"})
    assert existing[DETAILS_KEY] == {"expected_return": "5%"}


# --- staff editing a listing they don't own ---------------------------------

def test_staff_may_set_descriptive_fields():
    ensure_staff_edit_scope(list(REQUIRED_DETAIL_FIELDS) + ["overview", "faqs"])


@pytest.mark.parametrize("field", TERMS_FIELDS)
def test_staff_terms_edits_are_rejected(field):
    with pytest.raises(ListingTermsOwnerOnly):
        ensure_staff_edit_scope([field])


def test_staff_scope_is_independent_of_listing_status():
    # Unlike ensure_update_allowed, this check has no status parameter at all
    # -- terms are owner-only everywhere, including draft/pending where the
    # OWNER could still edit them.
    with pytest.raises(ListingTermsOwnerOnly):
        ensure_staff_edit_scope(["title"])


# --- route wiring ---------------------------------------------------------

def test_create_listing_enforces_the_required_details():
    import inspect

    from app.api.v1.marketplace import create_listing

    source = inspect.getsource(create_listing)
    assert "missing_required_details(" in source
    assert "MISSING_LISTING_DETAILS" in source


def test_update_listing_uses_the_status_policy_not_a_hardcoded_status_list():
    import inspect

    from app.api.v1.marketplace import update_listing

    source = inspect.getsource(update_listing)
    assert "ensure_update_allowed(" in source, (
        "update_listing must go through the policy"
    )
    assert "Can only update draft or pending listings" not in source, (
        "the blanket status refusal is what froze live listings at N/A"
    )


def test_update_listing_lets_staff_through_scoped_to_descriptive_fields():
    """Staff (admin, or an advisor for an assigned client) editing a listing
    they don't own must go through the moderation check and the owner-only
    terms guard -- not the old account_id-scoped lookup, which 404'd for
    every staff member since staff don't own the seller's listing."""
    import inspect

    from app.api.v1.marketplace import update_listing

    source = inspect.getsource(update_listing)
    assert "_assert_can_moderate_listing(" in source
    assert "ensure_staff_edit_scope(" in source
    assert "MarketplaceListing.account_id == account.id" not in source, (
        "scoping the listing lookup to the caller's own account is what made "
        "staff edits 404 -- the listing must be looked up by id alone, with "
        "ownership/moderation checked afterward"
    )


def test_detail_fields_the_page_renders_are_all_writable_on_update():
    """ListingUpdate must accept every field the detail page reads, or a seller
    still cannot fix an N/A."""
    from app.api.v1.marketplace import ListingUpdate

    fields = ListingUpdate.model_fields
    for name in REQUIRED_DETAIL_FIELDS + ("slots_filled", "overview", "faqs"):
        assert name in fields, f"ListingUpdate cannot set {name}"
