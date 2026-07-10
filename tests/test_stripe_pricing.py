"""Price resolution: (plan_id, billing_cycle) -> Stripe price id.

An unset price id must RAISE, never fall through to a free/None subscription:
a falsy price id flowing into subscription creation would hand the customer a
plan nobody charged for.

Runs under pytest *or* standalone:  python tests/test_stripe_pricing.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.stripe_pricing import resolve_price_id


class _FakeSettings:
    STRIPE_PRICE_STARTER_MONTHLY = "price_starter_m"
    STRIPE_PRICE_STARTER_ANNUAL = "price_starter_a"
    STRIPE_PRICE_PRO_MONTHLY = "price_pro_m"
    STRIPE_PRICE_PRO_ANNUAL = "price_pro_a"
    STRIPE_PRICE_PREMIUM_MONTHLY = "price_premium_m"
    STRIPE_PRICE_PREMIUM_ANNUAL = ""  # deliberately unset


def test_resolves_each_known_pair():
    s = _FakeSettings()
    assert resolve_price_id("starter", "monthly", settings_obj=s) == "price_starter_m"
    assert resolve_price_id("starter", "annual", settings_obj=s) == "price_starter_a"
    assert resolve_price_id("pro", "monthly", settings_obj=s) == "price_pro_m"
    assert resolve_price_id("pro", "annual", settings_obj=s) == "price_pro_a"
    assert resolve_price_id("premium", "monthly", settings_obj=s) == "price_premium_m"


def test_unset_price_raises_not_returns_none():
    s = _FakeSettings()
    try:
        resolve_price_id("premium", "annual", settings_obj=s)
    except ValueError as e:
        assert "STRIPE_PRICE_PREMIUM_ANNUAL" in str(e)
    else:
        raise AssertionError("unset price id must raise ValueError")


def test_unknown_plan_or_cycle_raises():
    s = _FakeSettings()
    for plan, cycle in [("gold", "monthly"), ("pro", "weekly")]:
        try:
            resolve_price_id(plan, cycle, settings_obj=s)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {plan}/{cycle}")


if __name__ == "__main__":
    test_resolves_each_known_pair()
    test_unset_price_raises_not_returns_none()
    test_unknown_plan_or_cycle_raises()
    print("OK  tests/test_stripe_pricing.py")
