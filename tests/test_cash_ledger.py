"""Pure-math tests for app/services/cash_ledger.py.

Trades used to write an Order row and nothing else — no cash ever moved, so
every balance the frontend showed was either a Plaid bank figure or the shared
app-level Alpaca paper account. These pin the signed-delta arithmetic the cash
ledger uses to debit buys, credit sells and reject unaffordable orders.
"""
import asyncio
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import List
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.cash import CashEntryType
from app.services.cash_ledger import (
    apply_delta,
    has_sufficient_funds,
    normalize_side,
    order_cash_delta,
    order_notional,
    record_cash_movement,
)


# --- side normalization ---------------------------------------------------

def test_normalize_side_accepts_case_and_whitespace():
    assert normalize_side(" BUY ") == "buy"
    assert normalize_side("Sell") == "sell"


def test_normalize_side_rejects_unknown_side():
    # A typo'd side must never silently become a credit.
    with pytest.raises(ValueError):
        normalize_side("byu")


# --- notional -------------------------------------------------------------

def test_order_notional_is_quantity_times_price():
    assert order_notional(Decimal("3"), Decimal("250.00")) == Decimal("750.00")


def test_order_notional_without_price_is_zero():
    # Quote misses leave price None; that must not blow up the funds check.
    assert order_notional(Decimal("3"), None) == Decimal("0.00")


def test_order_notional_rounds_to_cents_half_up():
    # 0.15 * 10.101 = 1.51515 -> 1.52
    assert order_notional(Decimal("0.15"), Decimal("10.101")) == Decimal("1.52")


def test_order_notional_accepts_floats_without_binary_artifacts():
    assert order_notional(0.1, 0.2) == Decimal("0.02")


# --- signed delta ---------------------------------------------------------

def test_buy_delta_is_negative():
    assert order_cash_delta("buy", Decimal("2"), Decimal("100.00")) == Decimal("-200.00")


def test_sell_delta_is_positive():
    assert order_cash_delta("sell", Decimal("2"), Decimal("100.00")) == Decimal("200.00")


def test_delta_without_price_is_zero_for_both_sides():
    # SUBMITTED orders with no execution price move no cash in either direction.
    assert order_cash_delta("buy", Decimal("2"), None) == Decimal("0.00")
    assert order_cash_delta("sell", Decimal("2"), None) == Decimal("0.00")


# --- funds check ----------------------------------------------------------

def test_exact_balance_is_sufficient():
    assert has_sufficient_funds(Decimal("200.00"), Decimal("-200.00")) is True


def test_one_cent_short_is_insufficient():
    assert has_sufficient_funds(Decimal("199.99"), Decimal("-200.00")) is False


def test_sells_are_never_blocked_by_a_zero_balance():
    assert has_sufficient_funds(Decimal("0.00"), Decimal("200.00")) is True


def test_zero_delta_is_always_sufficient():
    assert has_sufficient_funds(Decimal("0.00"), Decimal("0.00")) is True


# --- applying the delta ---------------------------------------------------

def test_apply_delta_debits_a_buy():
    assert apply_delta(Decimal("500.00"), Decimal("-200.00")) == Decimal("300.00")


def test_apply_delta_credits_a_sell():
    assert apply_delta(Decimal("500.00"), Decimal("200.00")) == Decimal("700.00")


def test_apply_delta_treats_missing_balance_as_zero():
    # Accounts predating the migration have NULL cash_balance.
    assert apply_delta(None, Decimal("200.00")) == Decimal("200.00")


def test_apply_delta_returns_two_decimal_places():
    assert apply_delta(Decimal("0.005"), Decimal("0.00")) == Decimal("0.01")


# --- recording a movement -------------------------------------------------

@dataclass
class FakeAccount:
    id: UUID = field(default_factory=uuid4)
    cash_balance: Decimal = Decimal("0.00")


@dataclass
class FakeSession:
    """Just enough AsyncSession surface for the recorder: add() and nothing else."""
    added: List = field(default_factory=list)
    committed: bool = False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


def test_record_cash_movement_debits_the_account_balance():
    db, account = FakeSession(), FakeAccount(cash_balance=Decimal("1000.00"))

    asyncio.run(
        record_cash_movement(
            db, account, entry_type=CashEntryType.TRADE_BUY, delta=Decimal("-250.00")
        )
    )

    assert account.cash_balance == Decimal("750.00")


def test_record_cash_movement_appends_a_ledger_row_with_balance_after():
    db, account = FakeSession(), FakeAccount(cash_balance=Decimal("1000.00"))

    asyncio.run(
        record_cash_movement(
            db, account, entry_type=CashEntryType.TRADE_BUY, delta=Decimal("-250.00")
        )
    )

    assert len(db.added) == 1
    entry = db.added[0]
    assert entry.account_id == account.id
    assert entry.entry_type == CashEntryType.TRADE_BUY
    assert entry.amount == Decimal("-250.00")
    assert entry.balance_after == Decimal("750.00")


def test_record_cash_movement_does_not_commit():
    # The caller owns the transaction: the Order insert, the balance change and
    # the ledger row must land atomically or not at all.
    db, account = FakeSession(), FakeAccount(cash_balance=Decimal("1000.00"))

    asyncio.run(
        record_cash_movement(
            db, account, entry_type=CashEntryType.DEPOSIT, delta=Decimal("100.00")
        )
    )

    assert db.committed is False


def test_successive_movements_chain_the_balance():
    db, account = FakeSession(), FakeAccount(cash_balance=Decimal("0.00"))

    async def scenario():
        await record_cash_movement(
            db, account, entry_type=CashEntryType.DEPOSIT, delta=Decimal("500.00")
        )
        await record_cash_movement(
            db, account, entry_type=CashEntryType.TRADE_BUY, delta=Decimal("-120.50")
        )
        await record_cash_movement(
            db, account, entry_type=CashEntryType.TRADE_SELL, delta=Decimal("20.50")
        )

    asyncio.run(scenario())

    assert account.cash_balance == Decimal("400.00")
    assert [entry.balance_after for entry in db.added] == [
        Decimal("500.00"),
        Decimal("379.50"),
        Decimal("400.00"),
    ]


def test_record_cash_movement_carries_order_provenance():
    db, account = FakeSession(), FakeAccount(cash_balance=Decimal("1000.00"))
    order_id = uuid4()

    asyncio.run(
        record_cash_movement(
            db,
            account,
            entry_type=CashEntryType.TRADE_BUY,
            delta=Decimal("-250.00"),
            order_id=order_id,
            description="buy 2 AAPL",
        )
    )

    entry = db.added[0]
    assert entry.order_id == order_id
    assert entry.description == "buy 2 AAPL"


# --- route wiring ---------------------------------------------------------
# The original bug was not bad arithmetic — it was that place_order never
# called any of this. These guard the wiring itself.

def test_place_order_checks_funds_and_records_the_movement():
    import inspect

    from app.api.v1.portfolio import place_order

    source = inspect.getsource(place_order)
    assert "has_sufficient_funds(" in source, "place_order does not check trading cash"
    assert "INSUFFICIENT_FUNDS" in source, "place_order does not raise INSUFFICIENT_FUNDS"
    assert "record_cash_movement(" in source, "place_order writes an Order but moves no cash"


def test_funds_check_runs_before_the_broker_call():
    """An unaffordable order must be rejected locally, never filled at the
    broker and then refused — that would leave a real position with no ledger
    entry behind it."""
    import inspect

    from app.api.v1.portfolio import place_order

    source = inspect.getsource(place_order)
    assert source.index("has_sufficient_funds(") < source.index("AlpacaClient.create_")


def test_cash_movement_is_committed_with_the_order_not_before_it():
    """One transaction: flush to get order.id, record, then a single commit."""
    import inspect

    from app.api.v1.portfolio import place_order

    source = inspect.getsource(place_order)
    assert source.index("db.flush()") < source.index("record_cash_movement(")
    assert source.index("record_cash_movement(") < source.index("db.commit()")


def test_brokerage_accounts_report_the_callers_own_balance():
    """This endpoint used to return AlpacaClient.get_account()'s figures, which
    come from shared app-level credentials — the same balance for every user."""
    import inspect

    from app.api.v1.portfolio import get_brokerage_accounts

    source = inspect.getsource(get_brokerage_accounts)
    assert "account.cash_balance" in source
    assert '"buying_power": account_data' not in source


def test_entry_type_column_sends_lowercase_values_not_member_names():
    """Without values_callable SQLAlchemy sends the member NAME ("DEPOSIT")
    while the PG type holds lowercase values, and every insert dies with
    InvalidTextRepresentation. Only reproducible against a real database, so
    pin the column config here."""
    from app.models.cash import CashTransaction

    column_type = CashTransaction.__table__.c.entry_type.type
    assert sorted(column_type.enums) == [
        "adjustment",
        "deposit",
        "trade_buy",
        "trade_sell",
        "withdrawal",
    ]
