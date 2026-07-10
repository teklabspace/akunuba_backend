"""Tests for the acquisition_date guard on AssetCreate / AssetUpdate.

A future acquisition date is impossible for an already-owned asset. Before this
guard, "Bitcoin Holding" was created with acquisition_date=2029-02-01 and only
the (quota-consuming) AI review caught it. Validate at the edge instead.

A small forward tolerance is allowed so a client in a timezone ahead of UTC can
submit its own "today" without being rejected.

Runs under pytest *or* standalone:  python tests/test_acquisition_date_validation.py
"""
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import ValidationError

from app.schemas.asset import AssetCreate, AssetUpdate, ACQUISITION_DATE_FUTURE_TOLERANCE


def _now():
    return datetime.now(timezone.utc)


@contextmanager
def _rejects(*, field="acquisition_date"):
    """Assert the block raises a ValidationError mentioning `field` and 'future'."""
    try:
        yield
    except ValidationError as exc:
        text = str(exc)
        assert field in text, f"error did not name {field!r}: {text}"
        assert "future" in text.lower(), f"error did not explain 'future': {text}"
        return
    raise AssertionError("expected a ValidationError, none was raised")


def test_past_acquisition_date_is_accepted():
    past = _now() - timedelta(days=365)
    assert AssetCreate(name="Rolex", acquisition_date=past).acquisition_date == past


def test_omitted_acquisition_date_is_accepted():
    assert AssetCreate(name="Rolex").acquisition_date is None
    assert AssetUpdate().acquisition_date is None


def test_far_future_acquisition_date_is_rejected():
    """The real bug: 2029-02-01 on a 2026 asset."""
    with _rejects():
        AssetCreate(name="Bitcoin Holding", acquisition_date=datetime(2029, 2, 1, tzinfo=timezone.utc))


def test_far_future_acquisition_date_is_rejected_on_update():
    with _rejects():
        AssetUpdate(acquisition_date=datetime(2029, 2, 1, tzinfo=timezone.utc))


def test_naive_past_datetime_is_accepted():
    """Legacy/naive payloads must not raise TypeError on naive-vs-aware compare."""
    naive_past = (_now() - timedelta(days=10)).replace(tzinfo=None)
    assert AssetCreate(name="Rolex", acquisition_date=naive_past).acquisition_date == naive_past


def test_naive_future_datetime_is_rejected():
    naive_future = (_now() + timedelta(days=900)).replace(tzinfo=None)
    with _rejects():
        AssetCreate(name="Rolex", acquisition_date=naive_future)


def test_timezone_skew_within_tolerance_is_accepted():
    """A client ahead of UTC submitting its own 'today' must not be rejected."""
    just_ahead = _now() + (ACQUISITION_DATE_FUTURE_TOLERANCE - timedelta(hours=1))
    assert AssetCreate(name="Rolex", acquisition_date=just_ahead).acquisition_date == just_ahead


def test_beyond_tolerance_is_rejected():
    beyond = _now() + ACQUISITION_DATE_FUTURE_TOLERANCE + timedelta(hours=2)
    with _rejects():
        AssetCreate(name="Rolex", acquisition_date=beyond)


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
        except Exception as e:  # noqa: BLE001 - surface unexpected errors as failures
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_standalone() else 0)
