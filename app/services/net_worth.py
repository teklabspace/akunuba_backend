"""Group-aware net-worth math shared by every portfolio/analytics/reports surface.

Product rule (client decision, 2026-07-13):

    net worth = (Assets + Portfolio + legacy ungrouped) - Liabilities

Liability amounts are stored as positive numbers in ``current_value`` and are
SUBTRACTED from totals here. Shadow Wealth, Philanthropy, Lifestyle, and
Governance are record-keeping groups: they never roll into net worth and are
surfaced as their own totals instead.

Any endpoint that shows a user-facing "portfolio value" / "total value" must go
through these helpers rather than summing ``current_value`` across all assets —
a raw sum counts a $2M mortgage as +$2M of wealth. Allocation, performance, and
risk math should run over ``core_assets(assets)`` only, so debts and
record-keeping entries don't skew percentages or returns.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional

from app.models.asset import CategoryGroup

# Groups whose value is wealth the user actually owns today. Legacy assets with
# no category_group predate the group system and were always counted — they
# stay in core so existing portfolios don't change.
CORE_GROUPS = frozenset({CategoryGroup.ASSETS, CategoryGroup.PORTFOLIO})

# Record-keeping groups: excluded from net worth, reported separately.
EXCLUDED_GROUPS = frozenset({
    CategoryGroup.SHADOW_WEALTH,
    CategoryGroup.PHILANTHROPY,
    CategoryGroup.LIFESTYLE,
    CategoryGroup.GOVERNANCE,
})


@dataclass
class NetWorthBreakdown:
    total_assets: Decimal        # gross owned wealth (core groups + legacy)
    total_liabilities: Decimal   # Liabilities group, stored positive
    net_worth: Decimal           # total_assets - total_liabilities
    shadow_wealth: Decimal       # anticipated, not owned — excluded
    philanthropy: Decimal        # irrevocably committed — excluded
    lifestyle: Decimal           # expenses/contracts — excluded
    governance: Decimal          # documents — excluded (normally 0)


def _group_of(asset) -> Optional[CategoryGroup]:
    """Normalize category_group to a CategoryGroup member (rows may carry raw strings)."""
    group = getattr(asset, "category_group", None)
    if group is None or isinstance(group, CategoryGroup):
        return group
    try:
        return CategoryGroup(group)
    except ValueError:
        return None


def _value_of(asset) -> Decimal:
    value = getattr(asset, "current_value", None)
    return value if value is not None else Decimal("0.00")


def is_core_asset(asset) -> bool:
    """True if the asset counts as owned wealth (allocation/performance/risk basis)."""
    group = _group_of(asset)
    return group is None or group in CORE_GROUPS


def core_assets(assets: Iterable) -> List:
    """The subset of assets that allocation, performance, and risk math run over."""
    return [asset for asset in assets if is_core_asset(asset)]


def compute_net_worth(assets: Iterable) -> NetWorthBreakdown:
    totals = {
        "core": Decimal("0.00"),
        CategoryGroup.LIABILITIES: Decimal("0.00"),
        CategoryGroup.SHADOW_WEALTH: Decimal("0.00"),
        CategoryGroup.PHILANTHROPY: Decimal("0.00"),
        CategoryGroup.LIFESTYLE: Decimal("0.00"),
        CategoryGroup.GOVERNANCE: Decimal("0.00"),
    }
    for asset in assets:
        group = _group_of(asset)
        key = "core" if group is None or group in CORE_GROUPS else group
        totals[key] += _value_of(asset)

    return NetWorthBreakdown(
        total_assets=totals["core"],
        total_liabilities=totals[CategoryGroup.LIABILITIES],
        net_worth=totals["core"] - totals[CategoryGroup.LIABILITIES],
        shadow_wealth=totals[CategoryGroup.SHADOW_WEALTH],
        philanthropy=totals[CategoryGroup.PHILANTHROPY],
        lifestyle=totals[CategoryGroup.LIFESTYLE],
        governance=totals[CategoryGroup.GOVERNANCE],
    )


def breakdown_dict(breakdown: NetWorthBreakdown) -> dict:
    """Uniform JSON blob every surface exposes as ``net_worth_breakdown``."""
    return {
        "total_assets": float(breakdown.total_assets),
        "total_liabilities": float(breakdown.total_liabilities),
        "net_worth": float(breakdown.net_worth),
        "shadow_wealth": float(breakdown.shadow_wealth),
        "philanthropy": float(breakdown.philanthropy),
        "lifestyle": float(breakdown.lifestyle),
    }
