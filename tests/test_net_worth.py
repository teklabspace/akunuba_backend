"""Tests for the group-aware net-worth helper (app/services/net_worth.py).

Product rule: net worth = (Assets + Portfolio + legacy ungrouped) - Liabilities.
Shadow Wealth / Philanthropy / Lifestyle / Governance are record-keeping groups:
excluded from net worth, surfaced as their own totals.

Pure-helper tests, no DB — run via pytest or `python tests/test_net_worth.py`.
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.asset import CategoryGroup
from app.services.net_worth import (
    breakdown_dict,
    compute_net_worth,
    core_assets,
    is_core_asset,
)


class StubAsset:
    def __init__(self, value, group):
        self.current_value = Decimal(str(value)) if value is not None else None
        self.category_group = group


def _mixed_assets():
    return [
        StubAsset("100.00", CategoryGroup.ASSETS),          # core
        StubAsset("200.00", CategoryGroup.PORTFOLIO),       # core
        StubAsset("50.00", None),                           # legacy ungrouped -> core
        StubAsset("120.00", CategoryGroup.LIABILITIES),     # subtracted
        StubAsset("500.00", CategoryGroup.SHADOW_WEALTH),   # excluded
        StubAsset("70.00", CategoryGroup.PHILANTHROPY),     # excluded
        StubAsset("30.00", CategoryGroup.LIFESTYLE),        # excluded
        StubAsset("0.00", CategoryGroup.GOVERNANCE),        # excluded
    ]


def test_net_worth_subtracts_liabilities_and_excludes_record_keeping_groups():
    b = compute_net_worth(_mixed_assets())
    assert b.total_assets == Decimal("350.00")
    assert b.total_liabilities == Decimal("120.00")
    assert b.net_worth == Decimal("230.00")
    assert b.shadow_wealth == Decimal("500.00")
    assert b.philanthropy == Decimal("70.00")
    assert b.lifestyle == Decimal("30.00")
    assert b.governance == Decimal("0.00")


def test_liability_never_counts_as_positive_wealth():
    # The original bug this helper exists to prevent: a $2M mortgage must
    # lower net worth, not raise it.
    b = compute_net_worth([
        StubAsset("1000000.00", CategoryGroup.ASSETS),
        StubAsset("2000000.00", CategoryGroup.LIABILITIES),
    ])
    assert b.net_worth == Decimal("-1000000.00")


def test_raw_string_category_groups_are_normalized():
    # DB rows can surface the enum as its raw string value.
    b = compute_net_worth([
        StubAsset("100.00", "Assets"),
        StubAsset("40.00", "Liabilities"),
        StubAsset("25.00", "Shadow Wealth"),
    ])
    assert b.total_assets == Decimal("100.00")
    assert b.total_liabilities == Decimal("40.00")
    assert b.net_worth == Decimal("60.00")
    assert b.shadow_wealth == Decimal("25.00")


def test_unknown_group_string_falls_back_to_core():
    # Garbage/unknown group labels behave like legacy ungrouped assets rather
    # than silently vanishing from every total.
    b = compute_net_worth([StubAsset("10.00", "Not A Real Group")])
    assert b.total_assets == Decimal("10.00")
    assert b.net_worth == Decimal("10.00")


def test_empty_and_none_values():
    b = compute_net_worth([])
    assert b.net_worth == Decimal("0.00")

    b = compute_net_worth([StubAsset(None, CategoryGroup.ASSETS)])
    assert b.total_assets == Decimal("0.00")


def test_core_assets_filter():
    assets = _mixed_assets()
    core = core_assets(assets)
    assert len(core) == 3
    assert all(is_core_asset(a) for a in core)
    assert not is_core_asset(StubAsset("1.00", CategoryGroup.LIABILITIES))
    assert not is_core_asset(StubAsset("1.00", CategoryGroup.LIFESTYLE))
    assert is_core_asset(StubAsset("1.00", None))


def test_breakdown_dict_shape():
    d = breakdown_dict(compute_net_worth(_mixed_assets()))
    assert d == {
        "total_assets": 350.0,
        "total_liabilities": 120.0,
        "net_worth": 230.0,
        "shadow_wealth": 500.0,
        "philanthropy": 70.0,
        "lifestyle": 30.0,
    }


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"[OK] {name}")
    print("All net-worth tests passed.")
