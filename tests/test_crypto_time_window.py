"""Pure tests for app/services/crypto_window.py.

Two reported crypto-portfolio bugs live here:

* the 24h dropdown "did nothing" — an unrecognised time_range silently fell
  through to `.get(time_range, 30)` and served 30 days of data, so unsupported
  options looked identical to the default instead of erroring;
* the date-range picker could not work at all — no crypto endpoint accepted a
  start/end date, only the fixed time_range enum.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.crypto_window import (
    SUPPORTED_TIME_RANGES,
    resolve_window,
    snapshot_points,
)

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


# --- the fixed dropdown options ------------------------------------------

def test_every_advertised_option_is_supported():
    # These are exactly the values the endpoint documents to the frontend.
    assert SUPPORTED_TIME_RANGES == ("1h", "6h", "12h", "24h", "7d", "30d", "1y")


def test_24h_window_spans_24_hours_back_from_now():
    window = resolve_window(time_range="24h", now=NOW)
    assert window.end == NOW
    assert window.start == NOW - timedelta(hours=24)


def test_7d_window_spans_seven_days():
    window = resolve_window(time_range="7d", now=NOW)
    assert window.start == NOW - timedelta(days=7)


def test_each_option_produces_a_distinct_span():
    spans = {
        option: resolve_window(time_range=option, now=NOW).end
        - resolve_window(time_range=option, now=NOW).start
        for option in SUPPORTED_TIME_RANGES
    }
    assert len(set(spans.values())) == len(SUPPORTED_TIME_RANGES)


def test_unknown_time_range_is_rejected_not_silently_defaulted():
    # The actual bug: "90d" used to return 30 days of data with a 200.
    with pytest.raises(ValueError):
        resolve_window(time_range="90d", now=NOW)


def test_missing_time_range_and_dates_is_rejected():
    with pytest.raises(ValueError):
        resolve_window(now=NOW)


# --- custom date range ----------------------------------------------------

def test_custom_range_uses_the_supplied_dates():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 3, 1, tzinfo=timezone.utc)
    window = resolve_window(start_date=start, end_date=end, now=NOW)
    assert (window.start, window.end) == (start, end)


def test_custom_range_overrides_time_range():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 3, 1, tzinfo=timezone.utc)
    window = resolve_window(time_range="24h", start_date=start, end_date=end, now=NOW)
    assert window.start == start


def test_custom_range_needs_both_ends():
    with pytest.raises(ValueError):
        resolve_window(start_date=datetime(2026, 1, 1, tzinfo=timezone.utc), now=NOW)
    with pytest.raises(ValueError):
        resolve_window(end_date=datetime(2026, 3, 1, tzinfo=timezone.utc), now=NOW)


def test_custom_range_rejects_end_before_start():
    with pytest.raises(ValueError):
        resolve_window(
            start_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            now=NOW,
        )


def test_custom_range_rejects_a_zero_length_span():
    same = datetime(2026, 3, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        resolve_window(start_date=same, end_date=same, now=NOW)


def test_naive_custom_dates_are_treated_as_utc():
    # Legacy/naive datetimes compared against aware ones raise TypeError —
    # a repeat offender in this codebase.
    window = resolve_window(
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 3, 1),
        now=NOW,
    )
    assert window.start.tzinfo is not None
    assert window.end.tzinfo is not None


# --- the points the chart is drawn from -----------------------------------

def test_intraday_points_are_labelled_by_clock_time():
    points = snapshot_points(resolve_window(time_range="24h", now=NOW))
    assert all(":" in label for _, label in points)


def test_multi_day_points_are_labelled_by_date():
    points = snapshot_points(resolve_window(time_range="30d", now=NOW))
    assert all("-" in label for _, label in points)


def test_a_one_day_custom_range_is_labelled_intraday():
    window = resolve_window(
        start_date=NOW - timedelta(hours=12), end_date=NOW, now=NOW
    )
    assert snapshot_points(window)[0][1].count(":") == 1


def test_points_are_ascending_and_end_at_the_window_end():
    points = snapshot_points(resolve_window(time_range="7d", now=NOW))
    dates = [dt for dt, _ in points]
    assert dates == sorted(dates)
    assert dates[-1] == NOW


def test_points_start_at_the_window_start():
    window = resolve_window(time_range="7d", now=NOW)
    assert snapshot_points(window)[0][0] == window.start


def test_a_very_long_custom_range_stays_bounded():
    # A 10-year range must not turn into thousands of per-point valuations.
    window = resolve_window(
        start_date=NOW - timedelta(days=3650), end_date=NOW, now=NOW
    )
    assert len(snapshot_points(window)) <= 366


def test_every_supported_option_yields_at_least_two_points():
    for option in SUPPORTED_TIME_RANGES:
        points = snapshot_points(resolve_window(time_range=option, now=NOW))
        assert len(points) >= 2, f"{option} produced {len(points)} point(s)"
