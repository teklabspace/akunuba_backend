"""Tests for escrow money movement (frontend request 2026-08-07).

Rules under test:
  - refunds return amount − commission (platform keeps its cut; configurable);
  - releases record a seller payout to their linked bank, with
    PAYOUT_ACCOUNT_MISSING / blocked_no_bank when no bank is linked;
  - every refund path uses the shared cents helper, every release path records
    the payout (route-wiring guards).

Pure-helper tests, no DB — run via pytest or
`python tests/test_escrow_payout.py`.
"""
import inspect
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services.escrow_payout import (
    PayoutStatus,
    bank_last4,
    escrow_net_amount,
    refund_cents,
)


def _escrow(amount, commission):
    return SimpleNamespace(amount=amount, commission=commission, currency="USD")


def test_net_amount_subtracts_commission():
    assert escrow_net_amount(_escrow(Decimal("2500.00"), Decimal("500.00"))) == Decimal("2000.00")


def test_net_amount_none_commission_is_full_amount():
    assert escrow_net_amount(_escrow(Decimal("100.00"), None)) == Decimal("100.00")


def test_net_amount_never_negative():
    # Defensive: bad data (commission > amount) must not produce a negative payout.
    assert escrow_net_amount(_escrow(Decimal("100.00"), Decimal("150.00"))) == Decimal("0")


def test_refund_cents_retains_commission_by_default():
    assert settings.ESCROW_REFUND_RETAINS_COMMISSION is True
    assert refund_cents(_escrow(Decimal("2500.00"), Decimal("500.00"))) == 200000


def test_refund_cents_full_refund_when_knob_off(monkeypatch):
    monkeypatch.setattr(settings, "ESCROW_REFUND_RETAINS_COMMISSION", False)
    assert refund_cents(_escrow(Decimal("2500.00"), Decimal("500.00"))) == 250000


def test_bank_last4_variants():
    assert bank_last4(SimpleNamespace(account_number="000123456789")) == "6789"
    # Plaid often returns a mask, not a full number.
    assert bank_last4(SimpleNamespace(account_number="****1234")) == "1234"
    assert bank_last4(SimpleNamespace(account_number="12")) == "12"
    assert bank_last4(SimpleNamespace(account_number=None)) is None


def test_payout_status_values_match_frontend_contract():
    # The frontend consumes these literal strings (pending|paid|blocked_no_bank|failed).
    assert {s.value for s in PayoutStatus} == {"pending", "paid", "blocked_no_bank", "failed"}


def test_release_routes_record_the_payout():
    """Route-wiring guard: every release path must go through prepare_seller_payout."""
    from app.api.v1.admin import admin_release_escrow, resolve_dispute
    from app.api.v1.marketplace import release_escrow

    for route in (release_escrow, admin_release_escrow, resolve_dispute):
        source = inspect.getsource(route)
        assert "prepare_seller_payout(" in source, (
            f"{route.__name__} does not record the seller payout"
        )


def test_seller_release_blocks_without_bank():
    from app.api.v1.marketplace import release_escrow

    source = inspect.getsource(release_escrow)
    assert "PAYOUT_ACCOUNT_MISSING" in source
    assert "resolve_payout_bank(" in source


def test_refund_routes_use_the_commission_aware_amount():
    """Route-wiring guard: every refund path refunds via refund_cents (net of
    commission), not a hand-rolled amount."""
    from app.api.v1.admin import _refund_escrow_via_stripe, resolve_dispute
    from app.api.v1.marketplace import refund_escrow

    for route in (refund_escrow, _refund_escrow_via_stripe, resolve_dispute):
        source = inspect.getsource(route)
        assert "refund_cents(" in source, (
            f"{route.__name__} does not use the commission-aware refund amount"
        )


def _run_standalone():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                if "monkeypatch" in inspect.signature(fn).parameters:
                    import pytest  # standalone still needs the fixture

                    class _MP:
                        def __init__(self):
                            self._undo = []

                        def setattr(self, obj, name_, value):
                            self._undo.append((obj, name_, getattr(obj, name_)))
                            setattr(obj, name_, value)

                        def undo(self):
                            for obj, name_, old in reversed(self._undo):
                                setattr(obj, name_, old)

                    mp = _MP()
                    try:
                        fn(mp)
                    finally:
                        mp.undo()
                else:
                    fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001 - surface any failure
                failures += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{'FAILED' if failures else 'OK'}")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_standalone() else 0)
