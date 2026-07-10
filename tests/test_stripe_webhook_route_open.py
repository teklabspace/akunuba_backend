"""Regression: the Stripe webhook must NOT sit behind an auth/KYC gate.

The bug this fixes: /api/v1/payments/webhook was mounted on the KYC-gated payments
router, so Stripe's unauthenticated POST got 401 and every event was dropped —
including a real payment_intent.succeeded (a customer paid and was never credited).
Any future move of this route back under a gated router must fail loudly here.

Runs under pytest *or* standalone:  python tests/test_stripe_webhook_route_open.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app


def _routes():
    return {getattr(r, "path", None): r for r in app.routes}


def test_stripe_webhook_route_exists():
    assert "/api/v1/webhooks/stripe" in _routes(), "canonical Stripe webhook route missing"


def test_stripe_webhook_has_no_auth_dependency():
    route = _routes()["/api/v1/webhooks/stripe"]
    names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
    for forbidden in ("get_current_user", "require_kyc_verified"):
        assert forbidden not in names, (
            f"{forbidden} guards the Stripe webhook; Stripe cannot authenticate. "
            "This is the exact bug that silently dropped every Stripe event."
        )


def test_dead_payments_webhook_is_gone():
    assert "/api/v1/payments/webhook" not in _routes(), "dead 401ing webhook still mounted"


def test_duplicate_subscriptions_webhook_is_gone():
    assert "/api/v1/subscriptions/webhook" not in _routes(), "duplicate Stripe webhook still mounted"


def test_persona_webhook_still_open():
    # Sanity: the router we're joining really is ungated.
    route = _routes()["/api/v1/webhooks/persona"]
    names = {getattr(d.call, "__name__", "") for d in route.dependant.dependencies}
    assert "require_kyc_verified" not in names


if __name__ == "__main__":
    test_stripe_webhook_route_exists()
    test_stripe_webhook_has_no_auth_dependency()
    test_dead_payments_webhook_is_gone()
    test_duplicate_subscriptions_webhook_is_gone()
    test_persona_webhook_still_open()
    print("OK  tests/test_stripe_webhook_route_open.py")
