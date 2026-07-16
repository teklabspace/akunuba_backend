"""Payment & subscription testing: plan catalog, feature gates, admin ops.

QA requirement: "Payment and subscription testing". Pins the plan catalog
(ids, prices, enum mappings — drift between any two of these maps produced
real 500s in the admin plan-change endpoint), the feature/limit ladders that
gate product capability by tier, and the admin subscription operations.

Runs under pytest *or* standalone:  python tests/test_payments_subscriptions.py
"""
import inspect
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.subscriptions import (
    PLAN_ENUM_TO_ID,
    PLAN_ID_TO_ENUM,
    PLAN_PRICES,
    normalize_plan_id,
)
from app.core.features import (
    FEATURE_LIMITS,
    Feature,
    PLAN_FEATURES,
    STORAGE_LIMITS,
    check_usage_limit,
    get_permissions,
    get_storage_limit,
    has_feature,
)
from app.models.payment import SubscriptionPlan


# ------------------------------------------------------------- plan catalog

def test_plan_price_catalog_shape():
    assert set(PLAN_PRICES) == {"starter", "pro", "premium"}
    for plan_id, prices in PLAN_PRICES.items():
        assert set(prices) == {"monthly", "annual"}, f"{plan_id} missing a billing cycle"
        for cycle, price in prices.items():
            assert isinstance(price, Decimal) and price > 0, (
                f"{plan_id}/{cycle} price must be a positive Decimal, got {price!r}"
            )


def test_annual_pricing_is_discounted_vs_monthly():
    # Annual ≈ 20% off 12× monthly; at minimum it must never cost MORE.
    for plan_id, prices in PLAN_PRICES.items():
        annual, monthly = prices["annual"], prices["monthly"]
        assert annual < monthly * 12, (
            f"{plan_id}: annual {annual} >= 12x monthly {monthly * 12} — discount inverted"
        )


def test_plan_id_and_enum_maps_are_inverse():
    for plan_id, enum in PLAN_ID_TO_ENUM.items():
        assert PLAN_ENUM_TO_ID[enum] == plan_id, (
            f"map drift: {plan_id} -> {enum} -> {PLAN_ENUM_TO_ID[enum]}"
        )
    assert set(PLAN_ENUM_TO_ID) == set(SubscriptionPlan), (
        "an internal plan enum has no product id mapping — admin plan ops will KeyError"
    )


def test_normalize_plan_id_accepts_legacy_prefixed_ids():
    # The frontend migrated from 'plan_starter' style ids; both forms must work.
    assert normalize_plan_id("starter") == "starter"
    assert normalize_plan_id("plan_starter") == "starter"
    assert normalize_plan_id("plan_premium") == "premium"
    assert normalize_plan_id(None) is None


def test_admin_plan_resolver_handles_all_alias_families():
    # Regression pin for the admin plan-change 500: every alias family the
    # admin UI has ever sent must resolve, and garbage must resolve to None
    # (which the endpoint turns into a 400, never a 500).
    from app.api.v1.admin import resolve_admin_plan_id

    assert resolve_admin_plan_id("pro") == "pro"
    assert resolve_admin_plan_id("plan_pro") == "pro"
    assert resolve_admin_plan_id("  PREMIUM ") == "premium"
    assert resolve_admin_plan_id("monthly") == "pro"      # legacy enum value
    assert resolve_admin_plan_id("annual") == "premium"   # legacy enum value
    assert resolve_admin_plan_id("free") == "starter"     # legacy enum value
    assert resolve_admin_plan_id("bogus-plan") is None
    assert resolve_admin_plan_id("") is None
    assert resolve_admin_plan_id(None) is None


def test_admin_plan_change_maps_defensively():
    # The handler must use .get() with defaults on every enum/price lookup so
    # unknown values 400 instead of 500 (the reported failure mode).
    from app.api.v1.admin import admin_change_subscription_plan

    src = inspect.getsource(admin_change_subscription_plan)
    assert "PLAN_ID_TO_ENUM.get(" in src, "unguarded enum lookup reintroduced"
    assert "BadRequestException" in src, "unknown plan must 400, not 500"


# ---------------------------------------------------------- feature ladders

def test_feature_ladder_is_monotonic_with_documented_upgrades():
    # Higher tiers keep every lower-tier capability; the only allowed swap is
    # a feature being SUPERSEDED by its unlimited variant.
    supersedes = {Feature.DOCUMENTS_BASIC: Feature.DOCUMENTS_UNLIMITED}

    def covered(feature, plan_features):
        return feature in plan_features or supersedes.get(feature) in plan_features

    free = set(PLAN_FEATURES[SubscriptionPlan.FREE])
    monthly = set(PLAN_FEATURES[SubscriptionPlan.MONTHLY])
    annual = set(PLAN_FEATURES[SubscriptionPlan.ANNUAL])

    for f in free:
        assert covered(f, monthly), f"MONTHLY lost FREE-tier capability {f}"
    for f in monthly:
        assert covered(f, annual), f"ANNUAL lost MONTHLY-tier capability {f}"


def test_premium_features_stay_premium():
    # These features are paid differentiators; appearing in FREE is a
    # monetization regression.
    for premium_only in (Feature.TRADING_ORDERS, Feature.BANKING, Feature.CHAT,
                         Feature.ANALYTICS_ADVANCED, Feature.REPORTS_PREMIUM):
        assert not has_feature(SubscriptionPlan.FREE, premium_only), (
            f"{premium_only} leaked into the FREE tier"
        )
    assert has_feature(SubscriptionPlan.ANNUAL, Feature.TRADING_ORDERS)
    assert has_feature(SubscriptionPlan.ANNUAL, Feature.BANKING)


def test_free_tier_can_still_transact_in_marketplace():
    # Product decision: FREE users browse and make (limited) offers.
    assert has_feature(SubscriptionPlan.FREE, Feature.MARKETPLACE_BROWSE)
    assert has_feature(SubscriptionPlan.FREE, Feature.MARKETPLACE_OFFER)
    assert not has_feature(SubscriptionPlan.FREE, Feature.MARKETPLACE_LIST), (
        "FREE tier must not create listings (listings limit is also 0)"
    )


def test_usage_limits_scale_upward():
    for key in ("assets", "documents", "listings"):
        free = FEATURE_LIMITS[SubscriptionPlan.FREE][key]
        monthly = FEATURE_LIMITS[SubscriptionPlan.MONTHLY][key]
        annual = FEATURE_LIMITS[SubscriptionPlan.ANNUAL][key]
        # None = unlimited, treated as infinity.
        as_num = lambda v: float("inf") if v is None else v
        assert as_num(free) <= as_num(monthly) <= as_num(annual), (
            f"limit '{key}' does not scale upward across tiers: {free}/{monthly}/{annual}"
        )


def test_unlimited_semantics_in_usage_check():
    assert check_usage_limit(SubscriptionPlan.ANNUAL, "offers", 10**9), (
        "None limit must mean unlimited"
    )
    assert not check_usage_limit(SubscriptionPlan.FREE, "assets", 5), (
        "FREE assets cap is 5 — the 6th create must be refused"
    )


def test_storage_limits_ladder():
    assert STORAGE_LIMITS[SubscriptionPlan.FREE] == 100 * 1024 * 1024
    assert STORAGE_LIMITS[SubscriptionPlan.MONTHLY] == 1024 * 1024 * 1024
    assert STORAGE_LIMITS[SubscriptionPlan.ANNUAL] == 10 * 1024 * 1024 * 1024
    assert get_storage_limit(SubscriptionPlan.FREE) == 100 * 1024 * 1024


def test_capability_flags_for_frontend():
    free_perms = get_permissions(SubscriptionPlan.FREE)
    annual_perms = get_permissions(SubscriptionPlan.ANNUAL)
    assert free_perms["can_trade"] is False and annual_perms["can_trade"] is True
    assert free_perms["can_use_banking"] is False and annual_perms["can_use_banking"] is True
    assert free_perms["can_list"] is False and annual_perms["can_list"] is True
    assert annual_perms["priority_support"] is True


# ------------------------------------------------------------- AI usage caps

def test_ai_usage_caps_per_plan():
    assert FEATURE_LIMITS[SubscriptionPlan.FREE]["ai_appraisals_per_month"] == 3
    assert FEATURE_LIMITS[SubscriptionPlan.MONTHLY]["ai_appraisals_per_month"] == 25
    assert FEATURE_LIMITS[SubscriptionPlan.ANNUAL]["ai_appraisals_per_month"] is None


def _run_standalone():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
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
