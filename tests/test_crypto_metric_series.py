"""Pure-math tests for the crypto performance metric shapes (QA finding B7:
all three metrics used to return the identical dollar series, so the frontend
labelled dollars as percentages — "1,800,000%" axes)."""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.crypto_metrics import metric_series


POINTS = [
    {"time": "2026-08-01", "value": 1000.0},
    {"time": "2026-08-02", "value": 1100.0},
    {"time": "2026-08-03", "value": 900.0},
]


def test_value_over_time_passthrough():
    out = metric_series(POINTS, "value-over-time")
    assert out == POINTS


def test_return_rate_is_percent_change_vs_first_point():
    out = metric_series(POINTS, "return-rate")
    assert [p["value"] for p in out] == [0.0, 10.0, -10.0]
    assert [p["time"] for p in out] == [p["time"] for p in POINTS]


def test_return_rate_zero_start_yields_zeros():
    pts = [{"time": "t1", "value": 0.0}, {"time": "t2", "value": 50.0}]
    out = metric_series(pts, "return-rate")
    assert [p["value"] for p in out] == [0.0, 0.0]


def test_risk_exposure_is_share_of_portfolio():
    denoms = [Decimal("2000"), Decimal("2200"), Decimal("4500")]
    out = metric_series(POINTS, "risk-exposure", exposure_denoms=denoms)
    assert [p["value"] for p in out] == [50.0, 50.0, 20.0]


def test_risk_exposure_zero_denominator_yields_zero():
    denoms = [Decimal("0"), Decimal("2200"), Decimal("0")]
    out = metric_series(POINTS, "risk-exposure", exposure_denoms=denoms)
    assert [p["value"] for p in out] == [0.0, 50.0, 0.0]


def test_unknown_metric_falls_back_to_values():
    assert metric_series(POINTS, "something-else") == POINTS


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
