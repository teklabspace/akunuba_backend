"""Pure-math tests for app/services/valuation_history.py.

These pin the as-of/first-value semantics the N+1 rewrite of
/investment/performance, /investment/analytics and /portfolio/summary relies
on — including the naive-vs-aware datetime normalization that has caused real
500s elsewhere in this codebase.
"""
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.valuation_history import first_value, value_asof


@dataclass
class FakeValuation:
    value: Decimal
    valuation_date: datetime


@dataclass
class FakeAsset:
    current_value: Decimal


ASSET = FakeAsset(current_value=Decimal("500.00"))


def _vals():
    # Deliberately mixed tz-awareness: DB rows are aware, snapshots often naive.
    return [
        FakeValuation(Decimal("100.00"), datetime(2026, 1, 1, tzinfo=timezone.utc)),
        FakeValuation(Decimal("200.00"), datetime(2026, 2, 1)),  # naive row
        FakeValuation(Decimal("300.00"), datetime(2026, 3, 1, tzinfo=timezone.utc)),
    ]


def test_value_asof_picks_latest_on_or_before():
    when = datetime(2026, 2, 15)  # naive query date
    assert value_asof(_vals(), ASSET, when) == Decimal("200.00")


def test_value_asof_aware_query_date_against_naive_row():
    when = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
    assert value_asof(_vals(), ASSET, when) == Decimal("200.00")


def test_value_asof_before_first_falls_back_to_first_valuation():
    when = datetime(2025, 6, 1)
    assert value_asof(_vals(), ASSET, when) == Decimal("100.00")


def test_value_asof_after_last_picks_last():
    when = datetime(2027, 1, 1)
    assert value_asof(_vals(), ASSET, when) == Decimal("300.00")


def test_value_asof_no_valuations_uses_current_value():
    assert value_asof([], ASSET, datetime(2026, 1, 1)) == Decimal("500.00")


def test_first_value_returns_earliest():
    assert first_value(_vals(), ASSET) == Decimal("100.00")


def test_first_value_no_valuations_uses_current_value():
    assert first_value([], ASSET) == Decimal("500.00")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
