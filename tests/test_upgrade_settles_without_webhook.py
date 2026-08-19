"""An upgrade must be able to land WITHOUT the customer.subscription.updated webhook.

Regression cover for a paid upgrade stranding the user on the frontend's
"Payment received / activating your plan" screen indefinitely: the upgrade left the
row ACTIVE, the GET self-heal only ran for INCOMPLETE rows, and the plan sync read
price metadata that a hand-created price may not carry.
"""
import pytest

from app.api.v1.webhooks import _plan_from_stripe_subscription
from app.core.stripe_pricing import resolve_plan_from_price_id


class _Cfg:
    STRIPE_PRICE_STARTER_MONTHLY = "price_starter_m"
    STRIPE_PRICE_STARTER_ANNUAL = "price_starter_a"
    STRIPE_PRICE_PRO_MONTHLY = "price_pro_m"
    STRIPE_PRICE_PRO_ANNUAL = "price_pro_a"
    STRIPE_PRICE_PREMIUM_MONTHLY = "price_premium_m"
    STRIPE_PRICE_PREMIUM_ANNUAL = "price_premium_a"


def _sub(price_id, metadata):
    return {"items": {"data": [{"price": {"id": price_id, "metadata": metadata,
                                          "unit_amount": 89900}}]}}


# --- the reverse lookup ------------------------------------------------------
@pytest.mark.parametrize("price_id,want", [
    ("price_premium_m", ("premium", "monthly")),
    ("price_premium_a", ("premium", "annual")),
    ("price_starter_m", ("starter", "monthly")),
    ("price_unknown", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
])
def test_resolve_plan_from_price_id(price_id, want):
    assert resolve_plan_from_price_id(price_id, settings_obj=_Cfg) == want


# --- the plan sync no longer depends on price metadata -----------------------
def test_plan_sync_uses_metadata_when_present(monkeypatch):
    import app.core.stripe_pricing as sp
    monkeypatch.setattr(sp, "settings", _Cfg)
    tier, cycle, amount = _plan_from_stripe_subscription(
        _sub("price_premium_m", {"plan_tier": "premium", "billing_cycle": "monthly"})
    )
    assert (tier, cycle) == ("premium", "monthly")
    assert float(amount) == 899.0


def test_plan_sync_falls_back_when_metadata_missing(monkeypatch):
    """A price created without metadata used to yield (None, None) -> nothing written
    -> the plan never landed and the user waited forever with no error logged."""
    import app.core.stripe_pricing as sp
    monkeypatch.setattr(sp, "settings", _Cfg)
    tier, cycle, _ = _plan_from_stripe_subscription(_sub("price_premium_m", {}))
    assert (tier, cycle) == ("premium", "monthly")


def test_plan_sync_falls_back_on_partial_metadata(monkeypatch):
    import app.core.stripe_pricing as sp
    monkeypatch.setattr(sp, "settings", _Cfg)
    tier, cycle, _ = _plan_from_stripe_subscription(
        _sub("price_premium_a", {"plan_tier": "premium"})
    )
    assert (tier, cycle) == ("premium", "annual")


def test_plan_sync_gives_up_cleanly_on_unknown_price(monkeypatch):
    import app.core.stripe_pricing as sp
    monkeypatch.setattr(sp, "settings", _Cfg)
    assert _plan_from_stripe_subscription(_sub("price_mystery", {}))[:2] == (None, None)


# --- the inline-grant condition in the upgrade handler -----------------------
def _proration_paid(intent, latest_invoice):
    """Mirrors the guard in subscriptions.upgrade_subscription."""
    intent_status = intent.get("status")
    return intent_status == "succeeded" or (
        not intent.get("id") and (latest_invoice.get("amount_due") or 0) == 0
    )


@pytest.mark.parametrize("intent,invoice,want,why", [
    ({"id": "pi_1", "status": "succeeded"}, {"amount_due": 89900}, True,
     "saved card charged inline -> grant now, do not wait on a webhook"),
    ({"id": "pi_2", "status": "processing"}, {"amount_due": 89900}, False,
     "money still in flight -> must not grant yet"),
    ({"id": "pi_3", "status": "requires_payment_method"}, {"amount_due": 89900}, False,
     "auto-charge failed, user still owes -> must not grant"),
    ({"id": "pi_4", "status": "requires_action"}, {"amount_due": 89900}, False,
     "3DS pending -> must not grant"),
    ({}, {"amount_due": 0}, True,
     "nothing owed (downgrade credit / no-op) -> price already changed at Stripe"),
    ({}, {"amount_due": 5000}, False,
     "invoice owed but no intent yet -> must not grant"),
])
def test_inline_grant_condition(intent, invoice, want, why):
    assert _proration_paid(intent, invoice) is want, why
