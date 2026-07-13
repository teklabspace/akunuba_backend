"""Tests for the paid-but-stuck subscription self-heal.

Real production incident: the Stripe webhook endpoint was disabled, so
invoice.payment_succeeded never arrived — paid users stayed INCOMPLETE forever,
the frontend's "checking payment" screen never resolved, and re-login bounced
them back to checkout. GET /subscriptions now reconciles an INCOMPLETE row with
Stripe directly, so the frontend's own status poll performs the recovery.

Runs under pytest *or* standalone:  python tests/test_subscription_reconcile.py
"""
import asyncio
import inspect
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.subscriptions import reconcile_incomplete_with_stripe
from app.integrations.stripe_client import StripeClient
from app.models.payment import SubscriptionStatus


class FakeDb:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _sub_row():
    return SimpleNamespace(
        id="local-sub-1",
        status=SubscriptionStatus.INCOMPLETE,
        stripe_subscription_id="sub_stripe_1",
        current_period_start=None,
        current_period_end=None,
        plan_tier=None,
        billing_cycle=None,
        amount=None,
        cancelled_at=None,
    )


def _with_stripe_response(response, fn):
    original = StripeClient.retrieve_subscription
    StripeClient.retrieve_subscription = staticmethod(
        response if callable(response) else (lambda _id: response)
    )
    try:
        return fn()
    finally:
        StripeClient.retrieve_subscription = original


def test_paid_incomplete_is_promoted_to_active():
    stripe_sub = {
        "status": "active",
        "current_period_start": 1783000000,
        "current_period_end": 1785678000,
        "items": {"data": [{"price": {
            "unit_amount": 4900,
            "metadata": {"plan_tier": "starter", "billing_cycle": "monthly"},
        }}]},
    }
    row, db = _sub_row(), FakeDb()
    _with_stripe_response(stripe_sub, lambda: asyncio.run(
        reconcile_incomplete_with_stripe(db, row)))
    assert row.status == SubscriptionStatus.ACTIVE
    assert row.plan_tier == "starter"
    assert row.billing_cycle == "monthly"
    assert row.amount == Decimal("49.00")
    assert row.current_period_end == datetime.fromtimestamp(1785678000, tz=timezone.utc)
    assert db.commits == 1


def test_genuinely_unpaid_stays_incomplete():
    row, db = _sub_row(), FakeDb()
    _with_stripe_response({"status": "incomplete", "items": {"data": []}}, lambda: asyncio.run(
        reconcile_incomplete_with_stripe(db, row)))
    assert row.status == SubscriptionStatus.INCOMPLETE
    assert db.commits == 0


def test_stripe_canceled_maps_to_cancelled():
    row, db = _sub_row(), FakeDb()
    _with_stripe_response({"status": "canceled", "items": {"data": []}}, lambda: asyncio.run(
        reconcile_incomplete_with_stripe(db, row)))
    assert row.status == SubscriptionStatus.CANCELLED
    assert row.cancelled_at is not None
    assert db.commits == 1


def test_stripe_error_never_raises():
    def boom(_id):
        raise RuntimeError("stripe down")
    row, db = _sub_row(), FakeDb()
    _with_stripe_response(boom, lambda: asyncio.run(
        reconcile_incomplete_with_stripe(db, row)))
    assert row.status == SubscriptionStatus.INCOMPLETE
    assert db.commits == 0


def test_get_subscription_invokes_reconcile():
    # Source pin: GET /subscriptions must run the self-heal for INCOMPLETE rows,
    # otherwise a missed webhook strands paid users on the checkout loop again.
    from app.api.v1.subscriptions import get_subscription
    src = inspect.getsource(get_subscription)
    assert "reconcile_incomplete_with_stripe" in src


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
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_standalone() else 0)
