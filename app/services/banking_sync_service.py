"""
Banking sync service for scheduled and webhook-triggered sync.
Can be called from scheduler (no request context) or from API.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.banking import LinkedAccount, Transaction
from app.integrations.plaid_client import PlaidClient
from app.utils.logger import logger


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
            if acc.get("mask") == linked_account.account_number or acc.get("account_id") == linked_account.plaid_item_id:
                linked_account.balance = Decimal(str(acc.get("balances", {}).get("available", 0)))
                break
        linked_account.last_synced_at = datetime.utcnow()
        await db.commit()
        return True
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to refresh balance for {linked_account_id}: {e}")
        return False
