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
