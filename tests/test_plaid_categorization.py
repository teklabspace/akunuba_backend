"""Pure-mapping tests for app/services/plaid_categorization.py.

Plaid's account `type` (depository/credit/loan/investment/other) is what every
"is this cash?" filter across portfolio/investment/accounts/reports now keys
on. These pin that mapping plus the legacy 3-value AccountType it still feeds
(app/services/escrow_payout.py filters BANKING-only for payout eligibility).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decimal import Decimal

from app.models.banking import AccountType
from app.services.plaid_categorization import (
    PLAID_ACCOUNT_TYPES,
    category_from_plaid_type,
    extract_balance,
    legacy_account_type,
)


# --- category_from_plaid_type ----------------------------------------------

def test_known_plaid_types_pass_through_unchanged():
    for t in PLAID_ACCOUNT_TYPES:
        assert category_from_plaid_type(t) == t


def test_unknown_plaid_type_falls_back_to_other():
    # Plaid adds types over time; an unrecognized one must not crash or be
    # silently miscategorized as cash.
    assert category_from_plaid_type("brokerage_new_type_plaid_invents") == "other"


def test_missing_plaid_type_falls_back_to_other():
    # Pre-migration rows and any account Plaid didn't tag.
    assert category_from_plaid_type(None) == "other"


# --- legacy_account_type -----------------------------------------------------

def test_depository_maps_to_banking():
    # escrow_payout.resolve_payout_bank filters exactly this value.
    assert legacy_account_type("depository") == AccountType.BANKING


def test_investment_maps_to_brokerage():
    assert legacy_account_type("investment") == AccountType.BROKERAGE


def test_credit_and_loan_map_to_other_not_banking():
    # A credit card or mortgage must never be payout-eligible via the BANKING filter.
    assert legacy_account_type("credit") == AccountType.OTHER
    assert legacy_account_type("loan") == AccountType.OTHER


def test_unknown_category_maps_to_other():
    assert legacy_account_type("other") == AccountType.OTHER
    assert legacy_account_type("something_unrecognized") == AccountType.OTHER


# --- extract_balance ---------------------------------------------------------
# Plaid's "available" is commonly null for credit/investment/loan accounts
# (Phase 1 only ever linked depository accounts, where it's usually populated,
# which is how `Decimal(str(acc["balances"].get("available", 0)))` stayed
# unnoticed — that call crashes the instant "available" is present-but-None,
# since .get(key, default) only returns the default when the KEY is missing).

def test_prefers_current_over_available():
    assert extract_balance({"current": 100.0, "available": 40.0}) == Decimal("100.0")


def test_falls_back_to_available_when_current_missing():
    assert extract_balance({"available": 40.0}) == Decimal("40.0")


def test_current_present_but_none_falls_back_to_available():
    # Real Plaid shape for some account types: the key exists with value null.
    assert extract_balance({"current": None, "available": 40.0}) == Decimal("40.0")


def test_both_missing_or_none_is_zero_not_a_crash():
    assert extract_balance({}) == Decimal("0")
    assert extract_balance({"current": None, "available": None}) == Decimal("0")


def test_accepts_none_balances_dict():
    # acc_data.get("balances") itself can be missing entirely.
    assert extract_balance(None) == Decimal("0")
