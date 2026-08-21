"""Maps Plaid's account taxonomy to the categories the rest of the app keys on.

Plaid tags every linked account with a primary `type` (depository, credit,
loan, investment, or other) and a more granular `subtype` (checking, credit
card, mortgage, brokerage, 401k, ...). `type` is stored as-is on
LinkedAccount.plaid_type and is what every "is this cash?" filter across
portfolio/investment/accounts/reports keys on directly (no separate derived
column - the mapping never needs more than the raw value itself).
"""
from decimal import Decimal
from typing import Optional

from app.models.banking import AccountType

# Plaid's four real primary types. Anything else (missing, or a type Plaid
# adds later) falls back to "other" rather than being silently treated as cash.
PLAID_ACCOUNT_TYPES = ("depository", "credit", "loan", "investment")


def plaid_value(value) -> Optional[str]:
    """Coerce a Plaid SDK field to plain text.

    The SDK hands back AccountType/AccountSubtype model objects rather than
    strings. They must be coerced before they reach either:
      * a String column - asyncpg raises DataError ("expected str, got
        AccountType") and the whole link fails; or
      * a string comparison - an object is never `in` a tuple of strings, so
        every account silently categorised as "other".
    """
    if value is None:
        return None
    return str(getattr(value, "value", value))


def category_from_plaid_type(plaid_type) -> str:
    """Plaid's raw `type`, normalized. Unknown or missing -> "other"."""
    normalized = plaid_value(plaid_type)
    return normalized if normalized in PLAID_ACCOUNT_TYPES else "other"


def legacy_account_type(category: str) -> AccountType:
    """The coarse 3(+1)-value AccountType the pre-categorization code still
    reads: app/services/escrow_payout.py filters BANKING-only for payout
    eligibility, and a couple of endpoints use it for a display label. Credit
    and loan accounts must resolve to OTHER, never BANKING - they are not
    valid payout destinations.
    """
    if category == "depository":
        return AccountType.BANKING
    if category == "investment":
        return AccountType.BROKERAGE
    return AccountType.OTHER


def extract_balance(balances: Optional[dict]) -> Decimal:
    """The account's headline balance from a Plaid `balances` object.

    Prefers `current` over `available`: `available` is commonly null for
    credit/loan/investment accounts (spendable-cash isn't a meaningful concept
    for a mortgage or a brokerage account), while `current` is populated for
    every account type Plaid supports. `.get(key, 0)` alone is not enough here
    — Plaid frequently sends the key present with an explicit null, which
    `.get` happily returns instead of falling through to the default.
    """
    balances = balances or {}
    current = balances.get("current")
    if current is not None:
        return Decimal(str(current))
    available = balances.get("available")
    if available is not None:
        return Decimal(str(available))
    return Decimal("0")
