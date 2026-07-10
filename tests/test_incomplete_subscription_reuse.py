"""Deciding what to do when a purchase lands on an existing INCOMPLETE subscription.

The bug this prevents: POST /subscriptions on an INCOMPLETE row fell through to the
overwrite branch, created a SECOND Stripe subscription, and overwrote
stripe_subscription_id with the new one. The first subscription stayed live in Stripe
with an open, payable invoice. If the customer paid THAT invoice, the webhook could no
longer match the subscription id and returned ignored_unknown_subscription — charged,
no access. Same failure class as the 401'd webhook.

Runs under pytest *or* standalone:  python tests/test_incomplete_subscription_reuse.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.stripe_client import (
    incomplete_subscription_action,
    subscription_price_id,
)


def _sub(status, price_id):
    return {
        "id": "sub_X",
        "status": status,
        "items": {"data": [{"id": "si_1", "price": {"id": price_id}}]},
    }


WANT = "price_pro_monthly"


def test_price_id_extraction():
    assert subscription_price_id(_sub("incomplete", WANT)) == WANT
    assert subscription_price_id({"items": {"data": []}}) is None
    assert subscription_price_id({}) is None
    assert subscription_price_id(None) is None


def test_no_prior_subscription_creates():
    assert incomplete_subscription_action(None, WANT) == "create"


def test_incomplete_same_plan_is_reused():
    # The user abandoned checkout and came back for the SAME plan. Hand them the
    # existing client_secret; do not mint a second subscription.
    assert incomplete_subscription_action(_sub("incomplete", WANT), WANT) == "reuse"


def test_incomplete_different_plan_is_replaced():
    # They changed their mind mid-checkout. The old one must be cancelled AND its
    # open invoice voided, or it stays payable behind their back.
    assert incomplete_subscription_action(_sub("incomplete", "price_premium_annual"), WANT) == "replace"


def test_live_subscription_is_a_conflict_not_a_second_charge():
    # Local row says INCOMPLETE but Stripe says paid: the webhook was missed. Never
    # create a second subscription here — that is the double-charge.
    for status in ("active", "trialing", "past_due"):
        assert incomplete_subscription_action(_sub(status, WANT), WANT) == "conflict"


def test_dead_subscription_creates_fresh():
    # Nothing left to orphan.
    for status in ("canceled", "incomplete_expired", "unpaid"):
        assert incomplete_subscription_action(_sub(status, WANT), WANT) == "create"


if __name__ == "__main__":
    test_price_id_extraction()
    test_no_prior_subscription_creates()
    test_incomplete_same_plan_is_reused()
    test_incomplete_different_plan_is_replaced()
    test_live_subscription_is_a_conflict_not_a_second_charge()
    test_dead_subscription_creates_fresh()
    print("OK  tests/test_incomplete_subscription_reuse.py")
