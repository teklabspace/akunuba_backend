"""Tests for listing detail-page helpers: performance math, document
file-type labels, and seller-provided detail fields stored in meta_data.
Pure/stub tests — no DB required.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.v1.marketplace import (  # noqa: E402
    ListingDetailFields,
    _apply_listing_details,
    _bucket_series,
    _document_file_type,
    _performance_metrics,
)


def _dt(days_ago):
    return datetime(2026, 7, 1, tzinfo=timezone.utc) - timedelta(days=days_ago)


def test_bucket_series_keeps_last_point_per_bucket():
    points = [(_dt(2), 100.0), (_dt(1), 110.0), (_dt(1), 115.0), (_dt(0), 120.0)]
    daily = _bucket_series(points, "daily")
    assert [v for _, v in daily] == [100.0, 115.0, 120.0]  # same-day dedup keeps last

    # May 22 / Jun 29+30 / Jul 1 -> last value of each month survives
    monthly = _bucket_series([(_dt(40), 90.0)] + points, "monthly")
    assert [v for _, v in monthly] == [90.0, 115.0, 120.0]


def test_performance_metrics_basic():
    points = [(_dt(365), 100000.0), (_dt(0), 112400.0)]
    m = _performance_metrics(points)
    assert m["total_return_pct"] == 12.4
    assert m["value_change_abs"] == 12400.0
    assert abs(m["annualized_return_pct"] - 12.4) < 0.1  # exactly one year
    assert m["volatility_pct"] == 0.0  # single interval, no dispersion


def test_performance_metrics_empty_and_degenerate():
    zeros = {"total_return_pct": 0.0, "annualized_return_pct": 0.0,
             "volatility_pct": 0.0, "value_change_abs": 0.0}
    assert _performance_metrics([]) == zeros
    assert _performance_metrics([(_dt(0), 100.0)]) == zeros
    assert _performance_metrics([(_dt(1), 0.0), (_dt(0), 50.0)]) == zeros  # zero start


def test_performance_metrics_short_window_not_annualized():
    m = _performance_metrics([(_dt(30), 100.0), (_dt(0), 946.31)])
    assert m["annualized_return_pct"] is None  # <90 days: annualizing is noise
    assert m["total_return_pct"] == 846.31


def test_performance_metrics_volatility_positive_when_returns_vary():
    points = [(_dt(3), 100.0), (_dt(2), 110.0), (_dt(1), 99.0), (_dt(0), 120.0)]
    m = _performance_metrics(points)
    assert m["volatility_pct"] > 0
    assert m["total_return_pct"] == 20.0


def test_document_file_type():
    assert _document_file_type(SimpleNamespace(mime_type="application/pdf", file_name="x.PDF")) == "pdf"
    assert _document_file_type(SimpleNamespace(
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_name="report.docx")) == "docx"
    assert _document_file_type(SimpleNamespace(mime_type=None, file_name="Deed.JPG")) == "jpg"
    assert _document_file_type(SimpleNamespace(mime_type="image/webp", file_name="photo")) == "webp"
    assert _document_file_type(SimpleNamespace(mime_type=None, file_name="noext")) is None


def test_apply_listing_details_merges_and_clears():
    listing = SimpleNamespace(meta_data=None, asset_id=uuid.uuid4())

    data = ListingDetailFields(
        expected_return="7.2%",
        duration="24 months",
        risk_level="low",
        slots_total=10,
        slots_filled=3,
        overview={"summary": "s", "investment_rationale": ["r1"],
                  "asset_security": "sec", "investment_objectives": ["o1"]},
        faqs=[{"question": "q", "answer": "a"}],
    )
    asyncio.run(_apply_listing_details(listing, data, db=None))  # no document_ids -> no DB use
    details = listing.meta_data["details"]
    assert details["expected_return"] == "7.2%"
    assert details["risk_level"] == "low"
    assert details["slots_total"] == 10
    assert details["overview"]["summary"] == "s"
    assert details["faqs"] == [{"question": "q", "answer": "a"}]

    # Partial update: change one field, explicitly clear another, leave rest.
    patch = ListingDetailFields(expected_return="8.0%", duration=None)
    asyncio.run(_apply_listing_details(listing, patch, db=None))
    details = listing.meta_data["details"]
    assert details["expected_return"] == "8.0%"
    assert "duration" not in details          # null cleared it
    assert details["risk_level"] == "low"     # untouched fields survive


if __name__ == "__main__":
    test_bucket_series_keeps_last_point_per_bucket()
    test_performance_metrics_basic()
    test_performance_metrics_empty_and_degenerate()
    test_performance_metrics_short_window_not_annualized()
    test_performance_metrics_volatility_positive_when_returns_vary()
    test_document_file_type()
    test_apply_listing_details_merges_and_clears()
    print("All tests passed")
