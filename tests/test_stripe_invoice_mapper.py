"""Stripe invoice -> payment-history item.

Stripe returns amounts in MINOR units (cents). Returning 29900 as a dollar total
would inflate the display by 100x. Status is Stripe's own vocabulary, not our
PaymentStatus enum, so callers must not map completed/failed onto it.

Runs under pytest *or* standalone:  python tests/test_stripe_invoice_mapper.py
"""
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.payments import _map_stripe_invoice


PAID = {
    "id": "in_1",
    "number": "ABCD1234-0001",
    "created": 1783684258,
    "total": 29900,
    "currency": "usd",
    "status": "paid",
    "hosted_invoice_url": "https://invoice.stripe.com/x",
    "invoice_pdf": "https://pay.stripe.com/x.pdf",
}


def test_minor_units_become_decimal_dollars():
    assert _map_stripe_invoice(PAID)["total"] == Decimal("299.00")


def test_currency_is_upper_cased():
    assert _map_stripe_invoice(PAID)["currency"] == "USD"


def test_invoice_number_and_status_pass_through():
    m = _map_stripe_invoice(PAID)
    assert m["invoice_number"] == "ABCD1234-0001"
    assert m["status"] == "paid"


def test_created_is_aware_utc():
    assert _map_stripe_invoice(PAID)["created_at"].tzinfo is not None


def test_draft_invoice_has_no_number():
    draft = dict(PAID, number=None, status="draft")
    assert _map_stripe_invoice(draft)["invoice_number"] is None
    assert _map_stripe_invoice(draft)["status"] == "draft"


def test_zero_total():
    assert _map_stripe_invoice(dict(PAID, total=0))["total"] == Decimal("0.00")


def test_annual_price_does_not_lose_precision():
    # 2870.00 -> 287000 cents. Float division would give 2869.9999999999995.
    assert _map_stripe_invoice(dict(PAID, total=287000))["total"] == Decimal("2870.00")


if __name__ == "__main__":
    test_minor_units_become_decimal_dollars()
    test_currency_is_upper_cased()
    test_invoice_number_and_status_pass_through()
    test_created_is_aware_utc()
    test_draft_invoice_has_no_number()
    test_zero_total()
    test_annual_price_does_not_lose_precision()
    print("OK  tests/test_stripe_invoice_mapper.py")
