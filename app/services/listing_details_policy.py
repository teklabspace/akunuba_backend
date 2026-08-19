"""What a marketplace listing must carry, and who may change it when.

Three rules live here, all from reported "N/A on the listing detail page" bugs:

1. ``expected_return``, ``duration``, ``risk_level`` and ``slots_total`` are
   REQUIRED at creation. They used to be optional, so sellers submitted
   listings without them and the detail page had nothing to show.

2. Those same fields — and the rest of the seller's marketing copy — stay
   editable while a listing is live. ``PUT /marketplace/listings/{id}`` used to
   refuse anything past ``pending_approval``, which froze the fields at
   approval and left every live listing permanently at "N/A" with no way for
   the seller to fix it.

3. Manual listing creation was removed (2026-08-18): the marketplace is now
   appraisal-driven only, and these four fields are supplied by staff at
   ``PUT /concierge/appraisals/{id}/valuation``, which is also what triggers
   auto-publish (see ``app.services.asset_listing_service``). Staff may also
   update descriptive fields on a listing they didn't create, through the same
   ``PUT /marketplace/listings/{id}`` endpoint the owner uses — scoped by
   ``ensure_staff_edit_scope`` below.

What does NOT stay editable — by the owner OR by staff — are the deal TERMS
(title, description, asking price): open offers and escrow amounts are priced
against them, so changing them under a live listing is a different and much
riskier operation. Terms remain the owner's alone to change.

Pure policy, no DB. Tested in ``tests/test_listing_details_policy.py``.
"""
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.models.marketplace import ListingStatus

# Must be supplied when a listing is created.
REQUIRED_DETAIL_FIELDS = (
    "expected_return",
    "duration",
    "risk_level",
    "slots_total",
)

# Every seller/staff-editable descriptive field, including the optional ones
# not in REQUIRED_DETAIL_FIELDS. Single source of truth for what lives under
# meta_data["details"] — marketplace.py and asset_listing_service.py both
# import this instead of keeping their own copy.
DETAIL_FIELD_NAMES = (
    "expected_return",
    "duration",
    "risk_level",
    "slots_total",
    "slots_filled",
    "overview",
    "faqs",
)

# meta_data key the detail fields are nested under.
DETAILS_KEY = "details"

# Priced-against fields. Locked once a listing goes live, and never
# staff-editable regardless of status.
TERMS_FIELDS = ("title", "description", "asking_price")

# Everything is editable here — the listing is not public yet.
FULLY_EDITABLE_STATUSES = frozenset({
    ListingStatus.DRAFT.value,
    ListingStatus.PENDING_APPROVAL.value,
})

# Live listings: descriptive fields only. SUSPENDED is included deliberately —
# it is a live listing temporarily pulled while an appraisal runs, and it gets
# restored, so excluding it would strand those listings at N/A all over again.
DETAIL_EDITABLE_STATUSES = frozenset({
    ListingStatus.APPROVED.value,
    ListingStatus.ACTIVE.value,
    ListingStatus.SUSPENDED.value,
})


class ListingEditError(ValueError):
    """Base for update-permission failures — catch this, raise a subclass.

    Deliberately carries no ``code`` of its own: it is never raised directly,
    and a placeholder here would show up as a phantom entry in the error-code
    contract (tests/test_error_code_drift.py).
    """
    code: str


class ListingNotEditable(ListingEditError):
    code = "LISTING_NOT_EDITABLE"


class ListingTermsLocked(ListingEditError):
    code = "LISTING_TERMS_LOCKED"


def _status_value(status: Any) -> str:
    """Accept a ListingStatus or a plain string."""
    return str(getattr(status, "value", status) or "").strip().lower()


def _is_blank(value: Any) -> bool:
    """Absent means None or an all-whitespace string. A numeric 0 is a real
    value — range checks are a separate concern from "you left this empty"."""
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def missing_required_details(provided: Mapping[str, Any]) -> List[str]:
    """Which required fields are absent or blank, in a stable order."""
    return [
        field
        for field in REQUIRED_DETAIL_FIELDS
        if field not in provided or _is_blank(provided[field])
    ]


def merge_details(existing_meta_data: Optional[Mapping[str, Any]], provided: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge provided detail fields into a listing's meta_data.

    Returns a NEW dict — JSONB columns don't track in-place mutation, so
    callers must reassign ``listing.meta_data`` to the result. Only keys
    present in ``provided`` change; an explicit ``None`` clears that key.
    Other meta_data keys (e.g. the public-documents opt-in list) pass through
    untouched.
    """
    meta = dict(existing_meta_data or {})
    details = dict(meta.get(DETAILS_KEY) or {})
    for field in DETAIL_FIELD_NAMES:
        if field in provided:
            if provided[field] is None:
                details.pop(field, None)
            else:
                details[field] = provided[field]
    meta[DETAILS_KEY] = details
    return meta


def ensure_update_allowed(status: Any, provided_fields: Iterable[str]) -> None:
    """Raise if this update is not permitted at the listing's current status.

    A request mixing terms and descriptive fields is rejected outright rather
    than partially applied — a silent partial write is worse than an error.
    """
    normalized = _status_value(status)

    if normalized in FULLY_EDITABLE_STATUSES:
        return

    if normalized not in DETAIL_EDITABLE_STATUSES:
        raise ListingNotEditable(
            f"A {normalized or 'closed'} listing can no longer be edited."
        )

    locked = [field for field in provided_fields if field in TERMS_FIELDS]
    if locked:
        raise ListingTermsLocked(
            f"{', '.join(locked)} cannot be changed once a listing is live — "
            "open offers and escrow are priced against these. "
            "Descriptive fields can still be updated."
        )


class ListingTermsOwnerOnly(ListingEditError):
    code = "LISTING_TERMS_OWNER_ONLY"


def ensure_staff_edit_scope(provided_fields: Iterable[str]) -> None:
    """Staff (admin, or an advisor moderating an assigned client's listing)
    may update descriptive fields on a listing they don't own. Terms stay
    under the owner's sole control, independent of the listing's status —
    this check applies whether or not ``ensure_update_allowed`` would
    otherwise permit the same fields.
    """
    locked = [field for field in provided_fields if field in TERMS_FIELDS]
    if locked:
        raise ListingTermsOwnerOnly(
            f"{', '.join(locked)} can only be changed by the listing's owner."
        )
