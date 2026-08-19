"""Trading cash ledger.

Placing a trade used to write an ``Order`` row and nothing else. No balance in
this codebase moved: ``/portfolio/summary``'s ``cash_available`` is a sum of
Plaid-synced bank balances, and ``/portfolio/trade-engine/accounts`` read the
*shared* app-credential Alpaca paper account, so it was identical for every
user. This module is the missing piece — an account-scoped cash balance
(``accounts.cash_balance``) with an append-only ``cash_transactions`` audit
trail behind it.

Money only moves for orders we consider settled (an execution price exists, so
the order is stored FILLED). A SUBMITTED limit/stop order is still checked
against the balance at placement — you cannot queue an order you could not
afford — but it moves no cash, because nothing in this codebase syncs an
Alpaca fill back into our ``orders`` table. When that sync is built, settle it
through ``record_cash_movement`` with ``CashEntryType.TRADE_BUY``/``TRADE_SELL``.

The pure helpers below hold every arithmetic rule and are unit-tested without a
database in ``tests/test_cash_ledger.py``.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash import CashEntryType, CashTransaction

BUY = "buy"
SELL = "sell"

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def _money(value: Any) -> Decimal:
    """Coerce anything numeric to a 2dp Decimal.

    Goes via ``str`` so a float argument cannot smuggle in binary artifacts
    (0.1 + 0.2 problems), and never mixes Decimal with float arithmetic — that
    raises TypeError and has caused real 500s in this codebase.
    """
    if value is None:
        return ZERO
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def normalize_side(side: Any) -> str:
    """``"BUY "`` -> ``"buy"``. Anything else is a programming error, not a credit."""
    normalized = str(side or "").strip().lower()
    if normalized not in (BUY, SELL):
        raise ValueError(f"Unknown order side: {side!r}")
    return normalized


def order_notional(quantity: Any, price: Any) -> Decimal:
    """Cash value of an order, rounded to cents. No price -> no known value."""
    if price is None or quantity is None:
        return ZERO
    quantity = quantity if isinstance(quantity, Decimal) else Decimal(str(quantity))
    price = price if isinstance(price, Decimal) else Decimal(str(price))
    return _money(quantity * price)


def order_cash_delta(side: Any, quantity: Any, price: Any) -> Decimal:
    """Signed cash movement: buys debit (negative), sells credit (positive)."""
    normalized = normalize_side(side)
    notional = order_notional(quantity, price)
    return -notional if normalized == BUY else notional


def has_sufficient_funds(balance: Any, delta: Any) -> bool:
    """True when applying ``delta`` keeps the balance at or above zero.

    Credits and zero-value movements always pass, so a sell is never blocked by
    an empty cash balance.
    """
    return _money(balance) + _money(delta) >= ZERO


def apply_delta(balance: Any, delta: Any) -> Decimal:
    """New balance after ``delta``. A NULL balance (pre-migration row) is 0.00."""
    return _money(_money(balance) + _money(delta))


async def record_cash_movement(
    db: AsyncSession,
    account,
    entry_type: CashEntryType,
    delta: Any,
    description: Optional[str] = None,
    order_id: Optional[UUID] = None,
    linked_account_id: Optional[UUID] = None,
) -> CashTransaction:
    """Move ``delta`` on the account balance and append the audit row.

    Adds to the session but does NOT commit — the caller owns the transaction
    so the balance change, the ledger row and whatever triggered them (an Order
    insert, a bank debit) land atomically or not at all.
    """
    delta = _money(delta)
    new_balance = apply_delta(account.cash_balance, delta)
    account.cash_balance = new_balance

    transaction = CashTransaction(
        account_id=account.id,
        entry_type=entry_type,
        amount=delta,
        balance_after=new_balance,
        description=description,
        order_id=order_id,
        linked_account_id=linked_account_id,
    )
    db.add(transaction)
    return transaction
