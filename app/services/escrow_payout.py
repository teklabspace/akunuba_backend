"""Escrow money movement: commission retention and seller payouts.

Client rule (2026-08-07 request): when an escrow ends, the platform keeps the
commission —
  - refund  -> buyer gets back amount − commission (partial Stripe card refund;
               set ESCROW_REFUND_RETAINS_COMMISSION=False for full refunds);
  - release -> seller is owed amount − commission, paid out to their
               Plaid-linked bank account.

Actual bank credits need Stripe Connect onboarding (not wired yet), so a
release records the payout: `payout_status` goes to PENDING with the resolved
bank's last4, or BLOCKED_NO_BANK + "link a bank account" email when the seller
has no active linked bank. `initiate_bank_payout` is the single seam where the
Connect/ACH rail plugs in later — everything else is already wired to it.
"""
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.utils.logger import logger


class PayoutStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    BLOCKED_NO_BANK = "blocked_no_bank"
    FAILED = "failed"


def escrow_net_amount(escrow) -> Decimal:
    """amount − commission, floored at 0 (None commission counts as 0)."""
    amount = escrow.amount or Decimal("0")
    commission = escrow.commission or Decimal("0")
    net = Decimal(amount) - Decimal(commission)
    return net if net > 0 else Decimal("0")


def refund_cents(escrow) -> int:
    """Stripe refund amount in cents: net of commission by default, full when
    ESCROW_REFUND_RETAINS_COMMISSION is off (product knob for dispute policy)."""
    if getattr(settings, "ESCROW_REFUND_RETAINS_COMMISSION", True):
        base = escrow_net_amount(escrow)
    else:
        base = Decimal(escrow.amount or 0)
    return int(base * 100)


def bank_last4(linked_account) -> Optional[str]:
    """Last 4 digits of the linked account's number (may be a Plaid mask)."""
    number = getattr(linked_account, "account_number", None)
    if not number:
        return None
    digits = "".join(ch for ch in str(number) if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else (digits or None)


async def resolve_payout_bank(db: AsyncSession, account_id):
    """The account's active BANKING-type linked account (most recent wins)."""
    from app.models.banking import AccountType as LinkedType, LinkedAccount

    return (await db.execute(
        select(LinkedAccount)
        .where(
            LinkedAccount.account_id == account_id,
            LinkedAccount.is_active.is_(True),
            LinkedAccount.account_type == LinkedType.BANKING,
        )
        .order_by(LinkedAccount.created_at.desc())
        .limit(1)
    )).scalars().first()


def initiate_bank_payout(escrow, bank) -> PayoutStatus:
    """Seam for the real money rail (Stripe Connect transfer / ACH credit).

    Not wired yet: the payout is recorded as PENDING for ops/finance to settle;
    when Connect onboarding lands, this is the only function that changes.
    """
    logger.info(
        "Payout recorded for escrow %s: %s %s to bank ****%s (pending settlement)",
        escrow.id, escrow_net_amount(escrow), escrow.currency, bank_last4(bank),
    )
    return PayoutStatus.PENDING


async def _payout_recipient(db: AsyncSession, account_id):
    """(email, first_name) of the user behind an account, or (None, None)."""
    from app.models.account import Account
    from app.models.user import User

    row = (await db.execute(
        select(User.email, User.first_name)
        .join(Account, Account.user_id == User.id)
        .where(Account.id == account_id)
    )).first()
    return (row[0], row[1]) if row else (None, None)


async def prepare_seller_payout(db: AsyncSession, escrow) -> PayoutStatus:
    """Resolve the seller's bank and stamp payout fields on the escrow row.

    No active linked bank -> BLOCKED_NO_BANK + 'link a bank account' email so
    the seller can unblock their own money. Never raises: releases must not
    fail because of payout bookkeeping. Caller commits.
    """
    from app.services.email_service import EmailService

    try:
        bank = await resolve_payout_bank(db, escrow.seller_id)
        if bank:
            escrow.payout_status = initiate_bank_payout(escrow, bank).value
            escrow.payout_destination_last4 = bank_last4(bank)
            return PayoutStatus(escrow.payout_status)

        escrow.payout_status = PayoutStatus.BLOCKED_NO_BANK.value
        escrow.payout_destination_last4 = None
        email, name = await _payout_recipient(db, escrow.seller_id)
        if email:
            await EmailService.send_payout_account_missing_email(
                to_email=email,
                to_name=name or "there",
                amount=float(escrow_net_amount(escrow)),
                currency=escrow.currency or "USD",
            )
        return PayoutStatus.BLOCKED_NO_BANK
    except Exception as e:  # noqa: BLE001 - payout bookkeeping must not block release
        logger.error(f"prepare_seller_payout failed for escrow {escrow.id}: {e}")
        escrow.payout_status = PayoutStatus.FAILED.value
        return PayoutStatus.FAILED
