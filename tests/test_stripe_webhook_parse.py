"""Stripe invoice -> subscription id extraction across API versions.

Our webhook endpoint is pinned to 2025-11-17.clover. From 2025-03-31.basil onward
Stripe REMOVED invoice.subscription and moved it to
invoice.parent.subscription_details.subscription. Reading the old path against a
new payload silently yields None and the subscription never activates — the same
failure mode as the Persona nested-inquiry-id bug.

The installed library (stripe==7.0.0) pins its own OUTBOUND api version; it has no
say over the shape of INBOUND webhook payloads. Those two are independent.

Runs under pytest *or* standalone:  python tests/test_stripe_webhook_parse.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.stripe_client import subscription_id_from_invoice


LEGACY_INVOICE = {
    "id": "in_legacy",
    "object": "invoice",
    "subscription": "sub_LEGACY123",
    "number": "ABCD1234-0001",
}

CLOVER_INVOICE = {
    "id": "in_clover",
    "object": "invoice",
    "number": "ABCD1234-0002",
    "parent": {
        "type": "subscription_details",
        "subscription_details": {"subscription": "sub_CLOVER456"},
    },
}

NO_SUBSCRIPTION_INVOICE = {"id": "in_oneoff", "object": "invoice", "number": "X-1"}


def test_legacy_shape():
    assert subscription_id_from_invoice(LEGACY_INVOICE) == "sub_LEGACY123"


def test_clover_shape():
    assert subscription_id_from_invoice(CLOVER_INVOICE) == "sub_CLOVER456"


def test_one_off_invoice_returns_none():
    assert subscription_id_from_invoice(NO_SUBSCRIPTION_INVOICE) is None


def test_subscription_may_be_expanded_object_not_string():
    # Stripe returns an expanded object when expand=["subscription"] was requested.
    inv = {"id": "in_exp", "subscription": {"id": "sub_EXPANDED", "object": "subscription"}}
    assert subscription_id_from_invoice(inv) == "sub_EXPANDED"


def test_empty_and_none_are_safe():
    assert subscription_id_from_invoice({}) is None
    assert subscription_id_from_invoice(None) is None


if __name__ == "__main__":
    test_legacy_shape()
    test_clover_shape()
    test_one_off_invoice_returns_none()
    test_subscription_may_be_expanded_object_not_string()
    test_empty_and_none_are_safe()
    print("OK  tests/test_stripe_webhook_parse.py")
