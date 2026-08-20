"""Feature entitlements, keyed on the product TIER the customer bought
(starter/pro/premium/concierge), never on billing cycle.

Bug fixed 2026-08-20: this used to key on ``SubscriptionPlan``
(free/monthly/annual), which is a billing CYCLE, not a tier -- see
``app.models.payment.SubscriptionPlan``. Every ANNUAL-only feature
(Banking, Trading Orders, Chat, ...) was unreachable by ANY monthly
subscriber regardless of tier, while a Starter *annual* subscriber got the
same feature set as a Premium subscriber. billing_cycle is a pricing/proration
detail and must never again factor into what a customer can access -- that's
the whole entitlement matrix's job, and the caller resolves the tier via
``app.api.v1.subscriptions.get_plan_tier`` before reaching this module.

"concierge" is a documented, not-yet-purchasable tier (no PLANS_CONFIG entry,
resolve_admin_plan_id() can't resolve it, zero live rows). Included here with
the same entitlements as "premium" so it isn't silently empty if it's ever
wired up.
"""
from enum import Enum
from typing import Dict, Optional

FREE = "free"
STARTER = "starter"
PRO = "pro"
PREMIUM = "premium"
CONCIERGE = "concierge"

PLAN_TIERS = (FREE, STARTER, PRO, PREMIUM, CONCIERGE)


class Feature(str, Enum):
    # Core Features
    DASHBOARD = "dashboard"
    ASSETS_VIEW = "assets_view"
    ASSETS_MANAGE = "assets_manage"
    PORTFOLIO_BASIC = "portfolio_basic"
    PORTFOLIO_ADVANCED = "portfolio_advanced"
    ACCOUNT_SETTINGS = "account_settings"
    SUPPORT_BASIC = "support_basic"
    SUPPORT_PRIORITY = "support_priority"
    NOTIFICATIONS = "notifications"
    DOCUMENTS_BASIC = "documents_basic"
    DOCUMENTS_UNLIMITED = "documents_unlimited"

    # Premium Features
    MARKETPLACE_BROWSE = "marketplace_browse"
    MARKETPLACE_LIST = "marketplace_list"
    MARKETPLACE_OFFER = "marketplace_offer"
    TRADING_VIEW = "trading_view"
    TRADING_ORDERS = "trading_orders"
    BANKING = "banking"
    CHAT = "chat"
    REPORTS_BASIC = "reports_basic"
    REPORTS_PREMIUM = "reports_premium"
    ANALYTICS_BASIC = "analytics_basic"
    ANALYTICS_ADVANCED = "analytics_advanced"


# Each tier is built as [previous tier] + [what that tier adds], so the
# "Everything in Pro, plus..." relationship in the pricing copy is explicit in
# code instead of three independently-typed lists that can silently drift.
_FREE_FEATURES = [
    Feature.DASHBOARD,
    Feature.ASSETS_VIEW,
    Feature.ASSETS_MANAGE,
    Feature.PORTFOLIO_BASIC,
    Feature.ACCOUNT_SETTINGS,
    Feature.SUPPORT_BASIC,
    Feature.NOTIFICATIONS,
    Feature.DOCUMENTS_BASIC,
    Feature.MARKETPLACE_BROWSE,
    Feature.MARKETPLACE_OFFER,
    Feature.TRADING_VIEW,
    Feature.REPORTS_BASIC,
]

# Starter ($49/mo, $470/yr): "Basic portfolio dashboard, limited aggregation
# (1-2 accounts), read-only market performance, marketplace browsing,
# standard email support." The "limited aggregation" IS Plaid banking --
# BANKING is a yes/no gate here, the "1-2 accounts" cap is enforced
# separately via PLANS_CONFIG[tier]["limits"]["max_accounts"].
_STARTER_FEATURES = _FREE_FEATURES + [
    Feature.DOCUMENTS_UNLIMITED,
    Feature.BANKING,
    Feature.ANALYTICS_BASIC,
]

# Pro ($299/mo, $2870/yr): "Full portfolio management, automated
# rebalancing, marketplace access, asset valuation tools, transaction
# tracking, priority support."
_PRO_FEATURES = _STARTER_FEATURES + [
    Feature.PORTFOLIO_ADVANCED,
    Feature.SUPPORT_PRIORITY,
    Feature.MARKETPLACE_LIST,
    Feature.TRADING_ORDERS,
    Feature.CHAT,
]

# Premium ($899/mo, $8630/yr): "Everything in Pro, AI-driven insights,
# automated asset valuation, document center, tax & investment advisory,
# premium support."
_PREMIUM_FEATURES = _PRO_FEATURES + [
    Feature.REPORTS_PREMIUM,
    Feature.ANALYTICS_ADVANCED,
]

PLAN_FEATURES: Dict[str, list] = {
    FREE: _FREE_FEATURES,
    STARTER: _STARTER_FEATURES,
    PRO: _PRO_FEATURES,
    PREMIUM: _PREMIUM_FEATURES,
    CONCIERGE: _PREMIUM_FEATURES,
}


# Numeric usage caps. Carried over directly from the old cycle-keyed values --
# FREE unchanged, {starter, pro} both inherit the old MONTHLY numbers, and
# {premium, concierge} both inherit the old ANNUAL numbers. This is a
# mechanical remap, not a fresh design pass: Starter and Pro (and Premium and
# Concierge) currently have IDENTICAL numeric limits. Differentiating them is
# a separate product decision, not part of this fix.
_FREE_LIMITS = {
    "assets": 5,
    "documents": 10,
    "listings": 0,
    "offers": 3,
    "trades": 0,
    "support_tickets": 1,
    # AI usage caps (per calendar month). None = unlimited.
    "ai_appraisals_per_month": 3,
    "ai_reviews_per_month": 3,
}

_STARTER_PRO_LIMITS = {
    "assets": 20,
    "documents": 50,
    "listings": 10,
    "offers": 20,
    "trades": 0,
    "support_tickets": None,
    "ai_appraisals_per_month": 25,
    "ai_reviews_per_month": 25,
}

_PREMIUM_CONCIERGE_LIMITS = {
    "assets": 100,
    "documents": 500,
    "listings": 50,
    "offers": None,
    "trades": None,
    "support_tickets": None,
    "ai_appraisals_per_month": None,
    "ai_reviews_per_month": None,
}

FEATURE_LIMITS: Dict[str, Dict[str, Optional[int]]] = {
    FREE: _FREE_LIMITS,
    STARTER: _STARTER_PRO_LIMITS,
    PRO: _STARTER_PRO_LIMITS,
    PREMIUM: _PREMIUM_CONCIERGE_LIMITS,
    CONCIERGE: _PREMIUM_CONCIERGE_LIMITS,
}


# Per-plan document storage limit in bytes. Same mechanical carryover as
# FEATURE_LIMITS above.
STORAGE_LIMITS: Dict[str, Optional[int]] = {
    FREE: 100 * 1024 * 1024,           # 100 MB
    STARTER: 1 * 1024 * 1024 * 1024,   # 1 GB (old MONTHLY value)
    PRO: 1 * 1024 * 1024 * 1024,       # 1 GB (old MONTHLY value)
    PREMIUM: 10 * 1024 * 1024 * 1024,  # 10 GB (old ANNUAL value)
    CONCIERGE: 10 * 1024 * 1024 * 1024,  # 10 GB (old ANNUAL value)
}


def get_storage_limit(plan: str) -> Optional[int]:
    """Document storage limit (bytes) for a plan tier. None means unlimited.
    An unrecognized tier fails safe to FREE's limit, not to unlimited."""
    return STORAGE_LIMITS.get(plan, STORAGE_LIMITS[FREE])


def get_plan_features(plan: str) -> list:
    """An unrecognized tier fails safe to FREE's feature list, not to []
    (which would also incorrectly zero out every FREE feature)."""
    return PLAN_FEATURES.get(plan, PLAN_FEATURES[FREE])


def has_feature(plan: str, feature: Feature) -> bool:
    return feature in get_plan_features(plan)


def get_plan_limits(plan: str) -> Dict[str, Optional[int]]:
    return FEATURE_LIMITS.get(plan, FEATURE_LIMITS[FREE])


def get_limit(plan: str, limit_type: str) -> Optional[int]:
    limits = get_plan_limits(plan)
    return limits.get(limit_type)


def get_permissions(plan: str) -> Dict[str, bool]:
    features = get_plan_features(plan)
    return {
        "can_trade": Feature.TRADING_ORDERS in features,
        "can_chat": Feature.CHAT in features,
        "can_list": Feature.MARKETPLACE_LIST in features,
        "can_use_banking": Feature.BANKING in features,
        "advanced_analytics": Feature.ANALYTICS_ADVANCED in features,
        "premium_reports": Feature.REPORTS_PREMIUM in features,
        "priority_support": Feature.SUPPORT_PRIORITY in features,
    }


def check_usage_limit(plan: str, limit_type: str, current_count: int) -> bool:
    """Check if current usage is within plan limits"""
    limit = get_limit(plan, limit_type)
    if limit is None:
        return True  # Unlimited
    return current_count < limit
