"""Maps a (plan_id, billing_cycle) pair to its Stripe Price id.

Pure lookup, no I/O. An unset price id raises rather than returning None: a falsy
price id would otherwise flow into subscription creation and hand the customer a
plan nobody charged for.
"""
from typing import Any

from app.config import settings

_VALID_TIERS = ("starter", "pro", "premium")
_VALID_CYCLES = ("monthly", "annual")


def resolve_price_id(plan_id: str, billing_cycle: str, settings_obj: Any = None) -> str:
    cfg = settings_obj if settings_obj is not None else settings

    if plan_id not in _VALID_TIERS:
        raise ValueError(f"Unknown plan_id: {plan_id!r}")
    if billing_cycle not in _VALID_CYCLES:
        raise ValueError(f"Unknown billing_cycle: {billing_cycle!r}")

    attr = f"STRIPE_PRICE_{plan_id.upper()}_{billing_cycle.upper()}"
    price_id = getattr(cfg, attr, "") or ""
    if not price_id:
        raise ValueError(
            f"{attr} is not configured. Subscription purchase cannot proceed "
            f"without a Stripe price id."
        )
    return price_id


def resolve_plan_from_price_id(price_id: str, settings_obj: Any = None):
    """Reverse of resolve_price_id: (plan_tier, billing_cycle) for a configured price
    id, or (None, None) if it matches none of them.

    Exists so we can identify the plan a Stripe subscription is on without depending on
    the price carrying plan_tier/billing_cycle in its metadata. That metadata is set by
    hand at catalog-creation time, and a price created without it silently breaks every
    sync path that reads it — the plan simply never lands locally. The configured price
    ids are the same mapping and are always present, so they make a reliable fallback.
    """
    cfg = settings_obj if settings_obj is not None else settings
    if not price_id:
        return None, None

    for tier in _VALID_TIERS:
        for cycle in _VALID_CYCLES:
            configured = getattr(cfg, f"STRIPE_PRICE_{tier.upper()}_{cycle.upper()}", "") or ""
            if configured and configured == price_id:
                return tier, cycle
    return None, None
