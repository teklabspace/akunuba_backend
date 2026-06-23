from enum import Enum
from typing import Dict, Optional
from app.models.payment import SubscriptionPlan


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


PLAN_FEATURES: Dict[SubscriptionPlan, list] = {
    SubscriptionPlan.FREE: [
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
    ],
    SubscriptionPlan.MONTHLY: [
        Feature.DASHBOARD,
        Feature.ASSETS_VIEW,
        Feature.ASSETS_MANAGE,
        Feature.PORTFOLIO_BASIC,
        Feature.ACCOUNT_SETTINGS,
        Feature.SUPPORT_BASIC,
        Feature.NOTIFICATIONS,
        Feature.DOCUMENTS_UNLIMITED,
        Feature.MARKETPLACE_BROWSE,
        Feature.MARKETPLACE_LIST,
        Feature.MARKETPLACE_OFFER,
        Feature.TRADING_VIEW,
        Feature.REPORTS_BASIC,
        Feature.ANALYTICS_BASIC,
    ],
    SubscriptionPlan.ANNUAL: [
        Feature.DASHBOARD,
        Feature.ASSETS_VIEW,
        Feature.ASSETS_MANAGE,
        Feature.PORTFOLIO_BASIC,
        Feature.PORTFOLIO_ADVANCED,
        Feature.ACCOUNT_SETTINGS,
        Feature.SUPPORT_BASIC,
        Feature.SUPPORT_PRIORITY,
        Feature.NOTIFICATIONS,
        Feature.DOCUMENTS_UNLIMITED,
        Feature.MARKETPLACE_BROWSE,
        Feature.MARKETPLACE_LIST,
        Feature.MARKETPLACE_OFFER,
        Feature.TRADING_VIEW,
        Feature.TRADING_ORDERS,
        Feature.BANKING,
        Feature.CHAT,
        Feature.REPORTS_BASIC,
        Feature.REPORTS_PREMIUM,
        Feature.ANALYTICS_BASIC,
        Feature.ANALYTICS_ADVANCED,
    ],
}


FEATURE_LIMITS: Dict[SubscriptionPlan, Dict[str, Optional[int]]] = {
    SubscriptionPlan.FREE: {
        "assets": 5,
        "documents": 10,
        "listings": 0,
        "offers": 3,
        "trades": 0,
        "support_tickets": 1,
        # AI usage caps (per calendar month). None = unlimited.
        "ai_appraisals_per_month": 3,
        "ai_reviews_per_month": 3,
    },
    SubscriptionPlan.MONTHLY: {
        "assets": 20,
        "documents": 50,
        "listings": 10,
        "offers": 20,
        "trades": 0,
        "support_tickets": None,
        "ai_appraisals_per_month": 25,
        "ai_reviews_per_month": 25,
    },
    SubscriptionPlan.ANNUAL: {
        "assets": 100,
        "documents": 500,
        "listings": 50,
        "offers": None,
        "trades": None,
        "support_tickets": None,
        "ai_appraisals_per_month": None,
        "ai_reviews_per_month": None,
    },
}


# Per-plan document storage limit in bytes. Adjust values to match product/billing.
STORAGE_LIMITS: Dict[SubscriptionPlan, Optional[int]] = {
    SubscriptionPlan.FREE: 100 * 1024 * 1024,        # 100 MB
    SubscriptionPlan.MONTHLY: 1 * 1024 * 1024 * 1024,  # 1 GB
    SubscriptionPlan.ANNUAL: 10 * 1024 * 1024 * 1024,  # 10 GB
}


def get_storage_limit(plan: SubscriptionPlan) -> Optional[int]:
    """Document storage limit (bytes) for a plan. None means unlimited."""
    return STORAGE_LIMITS.get(plan, STORAGE_LIMITS[SubscriptionPlan.FREE])


def get_plan_features(plan: SubscriptionPlan) -> list:
    return PLAN_FEATURES.get(plan, [])


def has_feature(plan: SubscriptionPlan, feature: Feature) -> bool:
    return feature in PLAN_FEATURES.get(plan, [])


def get_plan_limits(plan: SubscriptionPlan) -> Dict[str, Optional[int]]:
    return FEATURE_LIMITS.get(plan, {})


def get_limit(plan: SubscriptionPlan, limit_type: str) -> Optional[int]:
    limits = get_plan_limits(plan)
    return limits.get(limit_type)


def get_permissions(plan: SubscriptionPlan) -> Dict[str, bool]:
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


def check_usage_limit(plan: SubscriptionPlan, limit_type: str, current_count: int) -> bool:
    """Check if current usage is within plan limits"""
    limit = get_limit(plan, limit_type)
    if limit is None:
        return True  # Unlimited
    return current_count < limit

