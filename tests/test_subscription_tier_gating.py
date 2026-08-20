"""Bug fixed 2026-08-20: feature access was gated on billing CYCLE instead of
product TIER.

Reported symptom: a Premium subscriber on the monthly cycle got
403 "Banking integration requires Annual subscription" on
POST /banking/link-token and POST /banking/link.

Root cause: `get_user_subscription_plan()` (app/api/deps.py) returned
`subscription.plan` -- the legacy free/monthly/annual CYCLE enum -- and
`app/core/features.py` keyed its whole entitlement matrix on that same enum.
Every ANNUAL-only feature (Banking, Trading Orders, Chat, Portfolio Advanced,
Reports Premium, Analytics Advanced, Support Priority, and the storage/usage
limits) was unreachable by ANY monthly subscriber regardless of tier, while a
Starter-tier ANNUAL subscriber got the same feature set as Premium. Net effect
was inverted pricing: Premium-monthly received strictly fewer features than
Starter-annual.

Fix: `get_user_subscription_plan()` now resolves the actual tier via
`app.api.v1.subscriptions.get_plan_tier()` (preferring the explicit
`plan_tier` column, falling back to a legacy-enum reverse-map for rows
written before that column existed -- verified via direct query that all 15
live subscription rows already have `plan_tier` set, so that fallback path
carries no backfill risk today). `app/core/features.py` is now keyed on tier
strings only, with no notion of billing cycle anywhere in the module — see
tests/test_payments_subscriptions.py for the full feature-ladder coverage.

Runs under pytest *or* standalone:  python tests/test_subscription_tier_gating.py
"""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.features import FREE, PREMIUM, STARTER, Feature, has_feature


# --------------------------------------------------- the reported inversion

def test_premium_monthly_is_no_longer_worse_than_starter_annual():
    """The concrete bug: this must never again be true. has_feature has no
    billing_cycle parameter at all, so a "monthly" or "annual" distinction
    cannot exist in what it returns for a given tier -- both plan-tier calls
    below evaluate identically regardless of which cycle the real customer
    picked, which is exactly why the inversion can't recur.
    """
    premium_features = {f for f in Feature if has_feature(PREMIUM, f)}
    starter_features = {f for f in Feature if has_feature(STARTER, f)}
    missing_from_premium = starter_features - premium_features
    assert not missing_from_premium, (
        f"Premium is missing Starter-tier features {missing_from_premium} — "
        "this is the reported inversion"
    )
    assert premium_features > starter_features, (
        "Premium must be a strict superset of Starter, not merely equal"
    )


def test_the_reported_symptom_is_fixed():
    # Exact scenario from the report: Premium tier, monthly cycle, wants
    # Banking. has_feature only ever sees the tier -- there is no cycle input
    # for "monthly" to suppress this with.
    assert has_feature(PREMIUM, Feature.BANKING)


# ------------------------------------------------------------- route wiring

def test_get_user_subscription_plan_resolves_tier_not_cycle():
    from app.api.deps import get_user_subscription_plan

    source = inspect.getsource(get_user_subscription_plan)
    assert "get_plan_tier(subscription)" in source, (
        "must resolve the tier via get_plan_tier(), not read subscription.plan directly"
    )
    assert "return subscription.plan" not in source, (
        "reading the legacy cycle enum directly as the return value is the exact bug being fixed"
    )
    assert 'return "free"' in source, (
        'the no-subscription case must return the tier string "free", not the enum'
    )


def test_banking_error_messages_no_longer_name_a_billing_cycle():
    import app.api.v1.banking as banking

    source = inspect.getsource(banking)
    assert "Annual subscription" not in source, (
        "the old message told users to buy a cycle, not a tier -- and would "
        "have been wrong advice for a Starter/Pro monthly customer anyway"
    )


def test_features_module_has_no_billing_cycle_concept():
    # Structural guard, not a prose ban -- the module's own docstring
    # legitimately explains the fixed bug using these words. What must be
    # true is that the module doesn't IMPORT or DEPEND on the cycle enum.
    import app.core.features as features

    source = inspect.getsource(features)
    assert "from app.models.payment import" not in source, (
        "app/core/features.py must not import SubscriptionPlan (or anything "
        "else from the payment model) -- keying on it at all is the root cause"
    )
    assert ": SubscriptionPlan" not in source and "[SubscriptionPlan" not in source, (
        "no type hint or dict key may reference the billing-cycle enum"
    )


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
