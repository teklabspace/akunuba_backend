"""
Banking sync service for scheduled and webhook-triggered sync.
Can be called from scheduler (no request context) or from API.
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.banking import LinkedAccount, Transaction
from app.models.investment_holding import Security, InvestmentHolding
from app.models.liability import Liability
from app.integrations.plaid_client import PlaidClient
from app.services.plaid_categorization import extract_balance
from app.utils.logger import logger


def _parse_date(value) -> Optional[date]:
    """Plaid dates arrive as "YYYY-MM-DD" strings; tolerate an already-parsed
    date/datetime too rather than assume the exact shape."""
    if not value:
        return None
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    if hasattr(value, "date") and callable(value.date):
        return value.date()
    return value


def resolve_institution_name(access_token: str) -> Optional[str]:
    """The institution's real display name (e.g. "Chase"), not an account
    nickname. Best-effort: enrichment, never blocks the link flow — returns
    None on any failure."""
    try:
        item_response = PlaidClient.get_item(access_token)
        institution_id = (item_response.get("item") or {}).get("institution_id")
        if not institution_id:
            return None
        institution_response = PlaidClient.get_institution(institution_id)
        return (institution_response.get("institution") or {}).get("name")
    except Exception as e:
        logger.warning(f"Could not resolve Plaid institution name: {e}")
        return None


async def sync_linked_account_transactions(
    db: AsyncSession,
    linked_account_id: UUID,
) -> int:
    """
    Sync transactions for a single linked account. Used by scheduler and Plaid webhooks.
    Returns number of new transactions synced.
    """
    result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == linked_account_id,
            LinkedAccount.is_active == True,
        )
    )
    linked_account = result.scalar_one_or_none()
    if not linked_account:
        logger.warning(f"Linked account {linked_account_id} not found or inactive, skipping sync")
        return 0
    try:
        from datetime import timedelta
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        transactions_response = PlaidClient.get_transactions(
            access_token=linked_account.plaid_access_token,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
        )
        transactions_data = transactions_response.get("transactions", [])
        new_count = 0
        for tx_data in transactions_data:
            existing_result = await db.execute(
                select(Transaction).where(
                    Transaction.plaid_transaction_id == tx_data.get("transaction_id")
                )
            )
            if existing_result.scalar_one_or_none():
                continue
            transaction = Transaction(
                linked_account_id=linked_account.id,
                plaid_transaction_id=tx_data.get("transaction_id"),
                amount=Decimal(str(tx_data.get("amount", 0))),
                currency="USD",
                description=tx_data.get("name", ""),
                category=tx_data.get("category", [""])[0] if tx_data.get("category") else None,
                transaction_date=datetime.fromisoformat(tx_data.get("date", "")),
            )
            db.add(transaction)
            new_count += 1
        linked_account.last_synced_at = datetime.utcnow()
        await db.commit()
        logger.info(f"Synced {new_count} new transactions for linked account {linked_account_id}")
        return new_count
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to sync linked account {linked_account_id}: {e}", exc_info=True)
        raise


async def refresh_linked_account_balance(db: AsyncSession, linked_account_id: UUID) -> bool:
    """Refresh balance for a linked account. Used by scheduler and Plaid webhooks."""
    result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == linked_account_id,
            LinkedAccount.is_active == True,
        )
    )
    linked_account = result.scalar_one_or_none()
    if not linked_account:
        return False
    try:
        accounts_response = PlaidClient.get_accounts(linked_account.plaid_access_token)
        for acc in accounts_response.get("accounts", []):
            # plaid_account_id is the only identifier that safely disambiguates
            # multiple accounts under one Item — mask can collide, and
            # plaid_item_id is shared by every account under the Item, not
            # specific to one. Fall back to mask only for pre-migration rows
            # that never captured plaid_account_id.
            matches = (
                acc.get("account_id") == linked_account.plaid_account_id
                if linked_account.plaid_account_id
                else acc.get("mask") == linked_account.account_number
            )
            if matches:
                linked_account.balance = extract_balance(acc.get("balances"))
                break
        linked_account.last_synced_at = datetime.utcnow()
        await db.commit()
        return True
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to refresh balance for {linked_account_id}: {e}")
        return False


async def sync_linked_account_holdings(db: AsyncSession, linked_account_id: UUID) -> int:
    """Replace this account's investment holdings with Plaid's current
    snapshot. No-op for accounts that aren't investment-type. Used by
    scheduler and Plaid HOLDINGS webhooks.

    Plaid's /investments/holdings/get is a full current snapshot, not a
    delta, so holdings no longer reported for this account are deleted here
    rather than left stale.
    """
    result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == linked_account_id,
            LinkedAccount.is_active == True,
        )
    )
    linked_account = result.scalar_one_or_none()
    if not linked_account or linked_account.plaid_type != "investment":
        return 0
    try:
        response = PlaidClient.get_investment_holdings(linked_account.plaid_access_token)
        own_holdings = [
            h for h in response.get("holdings", [])
            if h.get("account_id") == linked_account.plaid_account_id
        ]
        needed_security_ids = {h.get("security_id") for h in own_holdings}
        securities_data = [
            s for s in response.get("securities", [])
            if s.get("security_id") in needed_security_ids
        ]

        security_row_by_plaid_id = {}
        for sec_data in securities_data:
            plaid_security_id = sec_data.get("security_id")
            existing = (await db.execute(
                select(Security).where(Security.plaid_security_id == plaid_security_id)
            )).scalar_one_or_none()
            if existing is None:
                existing = Security(plaid_security_id=plaid_security_id)
                db.add(existing)
            existing.ticker_symbol = sec_data.get("ticker_symbol")
            existing.name = sec_data.get("name")
            existing.security_type = sec_data.get("type")
            close_price = sec_data.get("close_price")
            existing.close_price = Decimal(str(close_price)) if close_price is not None else None
            existing.close_price_as_of = _parse_date(sec_data.get("close_price_as_of"))
            existing.currency = sec_data.get("iso_currency_code") or "USD"
            await db.flush()
            security_row_by_plaid_id[plaid_security_id] = existing

        now = datetime.utcnow()
        seen_security_row_ids = set()
        for h in own_holdings:
            security_row = security_row_by_plaid_id.get(h.get("security_id"))
            if security_row is None:
                continue
            holding = (await db.execute(
                select(InvestmentHolding).where(
                    InvestmentHolding.linked_account_id == linked_account.id,
                    InvestmentHolding.security_id == security_row.id,
                )
            )).scalar_one_or_none()
            if holding is None:
                holding = InvestmentHolding(
                    linked_account_id=linked_account.id, security_id=security_row.id
                )
                db.add(holding)
            quantity = h.get("quantity")
            holding.quantity = Decimal(str(quantity)) if quantity is not None else Decimal("0")
            cost_basis = h.get("cost_basis")
            holding.cost_basis = Decimal(str(cost_basis)) if cost_basis is not None else None
            institution_value = h.get("institution_value")
            holding.institution_value = (
                Decimal(str(institution_value)) if institution_value is not None else Decimal("0")
            )
            institution_price = h.get("institution_price")
            holding.institution_price = (
                Decimal(str(institution_price)) if institution_price is not None else None
            )
            holding.institution_price_as_of = _parse_date(h.get("institution_price_as_of"))
            holding.currency = h.get("iso_currency_code") or "USD"
            holding.last_synced_at = now
            await db.flush()
            seen_security_row_ids.add(security_row.id)

        existing_holdings = (await db.execute(
            select(InvestmentHolding).where(InvestmentHolding.linked_account_id == linked_account.id)
        )).scalars().all()
        for existing_holding in existing_holdings:
            if existing_holding.security_id not in seen_security_row_ids:
                await db.delete(existing_holding)

        linked_account.last_synced_at = now
        await db.commit()
        logger.info(f"Synced {len(seen_security_row_ids)} holdings for linked account {linked_account_id}")
        return len(seen_security_row_ids)
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to sync holdings for {linked_account_id}: {e}", exc_info=True)
        raise


async def sync_linked_account_liabilities(db: AsyncSession, linked_account_id: UUID) -> bool:
    """Replace this account's liability detail with Plaid's current snapshot.
    No-op for accounts that aren't credit/loan-type. Used by scheduler and
    Plaid LIABILITIES webhooks.

    The account's own balance (already captured by refresh_linked_account_balance
    via extract_balance) is the amount owed — Liabilities adds APR/statement/
    term detail on top of that, it does not duplicate the balance itself.
    """
    result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == linked_account_id,
            LinkedAccount.is_active == True,
        )
    )
    linked_account = result.scalar_one_or_none()
    if not linked_account or linked_account.plaid_type not in ("credit", "loan"):
        return False
    try:
        response = PlaidClient.get_liabilities(linked_account.plaid_access_token)
        liabilities_data = response.get("liabilities", {}) or {}

        matched_type = None
        matched_entry = None
        for bucket_type in ("credit", "mortgage", "student"):
            for entry in liabilities_data.get(bucket_type) or []:
                if entry.get("account_id") == linked_account.plaid_account_id:
                    matched_type = bucket_type
                    matched_entry = entry
                    break
            if matched_entry:
                break

        if matched_entry is None:
            return False

        liability = (await db.execute(
            select(Liability).where(Liability.linked_account_id == linked_account.id)
        )).scalar_one_or_none()
        if liability is None:
            liability = Liability(linked_account_id=linked_account.id)
            db.add(liability)

        def _decimal_or_none(key):
            value = matched_entry.get(key)
            return Decimal(str(value)) if value is not None else None

        liability.liability_type = matched_type
        liability.last_payment_amount = _decimal_or_none("last_payment_amount")
        liability.last_payment_date = _parse_date(matched_entry.get("last_payment_date"))
        liability.next_payment_due_date = _parse_date(matched_entry.get("next_payment_due_date"))
        liability.minimum_payment_amount = _decimal_or_none("minimum_payment_amount")
        liability.last_statement_balance = _decimal_or_none("last_statement_balance")
        liability.is_overdue = matched_entry.get("is_overdue")
        liability.details = matched_entry
        liability.last_synced_at = datetime.utcnow()

        linked_account.last_synced_at = liability.last_synced_at
        await db.commit()
        logger.info(f"Synced {matched_type} liability for linked account {linked_account_id}")
        return True
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to sync liabilities for {linked_account_id}: {e}", exc_info=True)
        raise
