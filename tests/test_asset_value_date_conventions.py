"""Tests for the QA findings of 2026-07-18 (asset create/edit pass):

- Value convention: an asset created with no monetary value stores 0.00 in
  BOTH current_value and estimated_value (never NULL-estimated + 0-current).
- Date convention: a date-only acquisition_date ("2021-07-15") is pinned to
  UTC midnight, never parsed in the server's local timezone; naive datetimes
  are persisted as UTC-aware.

Pure-helper tests, no DB — run via pytest or
`python tests/test_asset_value_date_conventions.py`.
"""
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.assets import resolve_initial_values
from app.schemas.asset import AssetCreate, AssetUpdate


# ---------------------------------------------------------------------------
# Value convention (QA finding #1)
# ---------------------------------------------------------------------------

def test_no_value_supplied_stores_zero_in_both_columns():
    current, estimated = resolve_initial_values(None, None)
    assert current == Decimal("0.00")
    assert estimated == Decimal("0.00")


def test_explicit_zero_matches_the_no_value_convention():
    # current_value: 0 with no estimate must not recreate the 0/NULL mix.
    current, estimated = resolve_initial_values(Decimal("0"), None)
    assert (current, estimated) == (Decimal("0.00"), Decimal("0.00"))


def test_current_only_keeps_estimated_null():
    # estimated_value = "appraised/estimated" — never fabricated from the
    # user-declared current_value.
    current, estimated = resolve_initial_values(Decimal("5000"), None)
    assert current == Decimal("5000")
    assert estimated is None


def test_estimated_only_promotes_to_current():
    current, estimated = resolve_initial_values(None, Decimal("3000"))
    assert current == Decimal("3000")
    assert estimated == Decimal("3000")


def test_both_supplied_are_stored_verbatim():
    current, estimated = resolve_initial_values(Decimal("5000"), Decimal("4500"))
    assert current == Decimal("5000")
    assert estimated == Decimal("4500")


# ---------------------------------------------------------------------------
# Date convention (QA finding #2)
# ---------------------------------------------------------------------------

def test_date_only_string_becomes_utc_midnight():
    asset = AssetCreate(name="QA", acquisition_date="2021-07-15")
    assert asset.acquisition_date == datetime(2021, 7, 15, tzinfo=timezone.utc)


def test_naive_datetime_is_persisted_as_utc():
    asset = AssetCreate(name="QA", acquisition_date=datetime(2021, 7, 15, 12, 30))
    assert asset.acquisition_date == datetime(2021, 7, 15, 12, 30, tzinfo=timezone.utc)


def test_aware_datetime_is_kept():
    aware = datetime(2021, 7, 15, 12, 30, tzinfo=timezone(timedelta(hours=5)))
    asset = AssetCreate(name="QA", acquisition_date=aware)
    assert asset.acquisition_date == aware


def test_update_schema_shares_the_normalization():
    update = AssetUpdate(acquisition_date="2021-07-15")
    assert update.acquisition_date == datetime(2021, 7, 15, tzinfo=timezone.utc)


def test_future_dates_still_rejected():
    next_month = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    with pytest.raises(ValueError):
        AssetCreate(name="QA", acquisition_date=next_month)


# ---------------------------------------------------------------------------
# Seed list mirrors the frontend's 90 sub-categories (QA finding #0)
# ---------------------------------------------------------------------------

def test_seed_list_covers_all_90_categories():
    from scripts.seed_categories import CATEGORIES

    names = [name for name, _, _, _ in CATEGORIES]
    assert len(names) == 90
    assert len(set(names)) == 90, "duplicate category names in seed list"

    # The 18 sub-categories QA found missing, plus the two Lifestyle entries
    # already auto-created in the shared DB.
    for required in [
        "Anticipated Exit Proceeds", "Brand / IP Equity", "Legal Settlements",
        "Marital / Shared Assets", "Trust Allocations",
        "Donor-Advised Funds", "Endowments", "Foundations",
        "Impact Investments", "Scholarship Trusts",
        "Club Memberships", "Event & Auction Access", "Family Office Services",
        "Insurance Management", "Property Maintenance", "Travel Concierge",
        "Audit Logs", "KYC & AML Records", "Legal Agreements",
        "Regulatory Filings",
    ]:
        assert required in names, f"missing from seed list: {required}"


def test_seed_list_groups_match_frontend():
    from app.models.asset import CategoryGroup
    from scripts.seed_categories import CATEGORIES

    by_group = {}
    for _, group, _, _ in CATEGORIES:
        by_group[group] = by_group.get(group, 0) + 1

    assert by_group == {
        CategoryGroup.ASSETS: 24,
        CategoryGroup.PORTFOLIO: 33,
        CategoryGroup.LIABILITIES: 10,
        CategoryGroup.SHADOW_WEALTH: 8,
        CategoryGroup.PHILANTHROPY: 5,
        CategoryGroup.LIFESTYLE: 6,
        CategoryGroup.GOVERNANCE: 4,
    }


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"[OK] {name}")
    print("All value/date convention tests passed.")
