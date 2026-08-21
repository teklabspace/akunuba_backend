from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from decimal import Decimal
from datetime import datetime, timedelta
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.banking import LinkedAccount, Transaction, AccountType
from app.models.investment_holding import Security, InvestmentHolding
from app.models.liability import Liability
from app.integrations.plaid_client import PlaidClient
from app.services.plaid_categorization import category_from_plaid_type, legacy_account_type, extract_balance, plaid_value
from app.services.banking_sync_service import (
    resolve_institution_name,
    refresh_linked_account_balance,
    sync_linked_account_holdings,
    sync_linked_account_liabilities,
)
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from app.api.deps import get_account, get_user_subscription_plan
from app.core.features import Feature, has_feature
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


class LinkTokenResponse(BaseModel):
    link_token: str


class LinkAccountRequest(BaseModel):
    public_token: str


class LinkedAccountResponse(BaseModel):
    id: UUID
    institution_name: str
    account_name: str
    account_type: str
    balance: Optional[Decimal] = None
    currency: str

    class Config:
        from_attributes = True


@router.post("/link-token", response_model=LinkTokenResponse)
async def create_link_token(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create Plaid link token for account linking.

    This endpoint creates a link token that the frontend uses to initialize
    Plaid Link for connecting bank accounts.

    Returns:
        LinkTokenResponse with link_token string

    Raises:
        404: If user account not found
        400: If Plaid credentials not configured or API call fails
    """
    # Verify user has an account record
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    # Gate before the Plaid widget ever opens — /banking/link enforces the
    # same rule, but failing only there means the user completes the whole
    # bank-selection flow and is rejected at the final step.
    plan = await get_user_subscription_plan(account=account, db=db)
    if not has_feature(plan, Feature.BANKING):
        raise ForbiddenException(
            "Banking integration requires a paid subscription (Starter plan or higher).",
            code="SUBSCRIPTION_REQUIRED",
        )

    try:
        link_token = PlaidClient.create_link_token(
            user_id=str(current_user.id),
            account_id=str(account.id)
        )
        logger.info(f"Link token created successfully for user {current_user.id}")
        return LinkTokenResponse(link_token=link_token)
    except ValueError as e:
        # Credentials not configured or SDK not available
        logger.error(f"Plaid configuration error: {e}")
        raise BadRequestException(f"Plaid not configured: {str(e)}")
    except Exception as e:
        # Plaid API error
        logger.error(f"Failed to create Plaid link token: {e}", exc_info=True)
        raise BadRequestException(f"Failed to create link token: {str(e)}")


@router.post("/link")
async def link_account(
    payload: LinkAccountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Link account(s) using a Plaid public token.

    Every account Plaid returns under this Item is stored as its own
    LinkedAccount with its own real Plaid type/subtype/id — a single
    institution login can return a checking, a savings, and a brokerage
    account together, and each keeps its own identity rather than being
    collapsed into one generic "banking" record.
    """
    public_token = payload.public_token
    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)

    # Check subscription feature
    if not has_feature(plan, Feature.BANKING):
        raise ForbiddenException(
            "Banking integration requires a paid subscription (Starter plan or higher).",
            code="SUBSCRIPTION_REQUIRED",
        )

    try:
        # Exchange public token for access token
        exchange_response = PlaidClient.exchange_public_token(public_token)
        access_token = exchange_response["access_token"]
        item_id = exchange_response["item_id"]

        # Get account information
        accounts_response = PlaidClient.get_accounts(access_token)
        accounts_data = accounts_response.get("accounts", [])

        if not accounts_data:
            raise BadRequestException("No accounts found")

        # Institution's real display name (e.g. "Chase"), not an account
        # nickname — best-effort, never blocks linking.
        institution_name = resolve_institution_name(access_token) or "Unknown Institution"

        linked_accounts = []
        for acc_data in accounts_data:
            # Coerced to text: the SDK returns AccountType/AccountSubtype
            # objects, which asyncpg refuses for these String columns and which
            # never match the string comparisons below.
            plaid_type = plaid_value(acc_data.get("type"))
            plaid_subtype = plaid_value(acc_data.get("subtype"))
            category = category_from_plaid_type(plaid_type)
            linked_account = LinkedAccount(
                account_id=account.id,
                plaid_item_id=item_id,
                plaid_account_id=acc_data.get("account_id"),
                plaid_access_token=access_token,
                account_type=legacy_account_type(category),
                plaid_type=plaid_type,
                plaid_subtype=plaid_subtype,
                institution_name=institution_name,
                account_name=acc_data.get("name", "Account"),
                account_number=acc_data.get("mask", ""),
                balance=extract_balance(acc_data.get("balances")),
                currency="USD",
                last_synced_at=datetime.utcnow(),
            )
            db.add(linked_account)
            linked_accounts.append(linked_account)

        await db.commit()

        # Best-effort first sync so a newly linked brokerage/credit/loan
        # account shows real holdings/liability data immediately instead of
        # waiting for the next 6-hour scheduled sync. Must not fail the link
        # itself — the account is linked either way.
        for linked_account in linked_accounts:
            try:
                if linked_account.plaid_type == "investment":
                    await sync_linked_account_holdings(db, linked_account.id)
                elif linked_account.plaid_type in ("credit", "loan"):
                    await sync_linked_account_liabilities(db, linked_account.id)
            except Exception as e:
                logger.warning(f"Initial sync failed for linked account {linked_account.id}: {e}")

        logger.info(f"Accounts linked for user {current_user.id}")
        return {"message": f"{len(linked_accounts)} account(s) linked successfully"}
    except BadRequestException:
        raise
    except Exception as e:
        logger.error(f"Failed to link account: {e}")
        raise BadRequestException("Failed to link account")


class BankingAccountResponse(BaseModel):
    id: UUID
    institution_name: str
    account_name: str
    account_type: str
    category: str
    subtype: Optional[str] = None
    balance: Optional[Decimal] = None
    currency: str
    last_synced: Optional[datetime] = None

    class Config:
        from_attributes = True


class BankingAccountsResponse(BaseModel):
    data: List[BankingAccountResponse]


@router.get("/accounts", response_model=BankingAccountsResponse)
async def get_linked_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all linked accounts, each tagged with its real Plaid category
    (depository/credit/loan/investment) so the frontend can place it under
    the correct portfolio section."""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.account_id == account.id,
            LinkedAccount.is_active == True
        )
    )
    linked_accounts = result.scalars().all()

    data = [
        BankingAccountResponse(
            id=linked_account.id,
            institution_name=linked_account.institution_name or "Unknown Institution",
            account_name=linked_account.account_name,
            # Plaid's own subtype (e.g. "checking", "credit card", "401k") is
            # already a display-ready label — more precise than the old
            # 3-value account_type map this replaces.
            account_type=linked_account.plaid_subtype or category_from_plaid_type(linked_account.plaid_type),
            category=category_from_plaid_type(linked_account.plaid_type),
            subtype=linked_account.plaid_subtype,
            balance=linked_account.balance,
            currency=linked_account.currency,
            last_synced=linked_account.last_synced_at
        )
        for linked_account in linked_accounts
    ]

    return BankingAccountsResponse(data=data)


@router.post("/sync/{linked_account_id}")
async def sync_transactions(
    linked_account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Sync transactions from linked account"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    linked_account_result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == linked_account_id,
            LinkedAccount.account_id == account.id
        )
    )
    linked_account = linked_account_result.scalar_one_or_none()

    if not linked_account:
        raise NotFoundException("Linked Account", str(linked_account_id))

    try:
        # Get transactions from last 30 days
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)

        transactions_response = PlaidClient.get_transactions(
            access_token=linked_account.plaid_access_token,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d")
        )

        transactions_data = transactions_response.get("transactions", [])

        # Store transactions
        new_count = 0
        for tx_data in transactions_data:
            # Check if transaction already exists
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

        logger.info(f"Synced {new_count} new transactions for account {linked_account_id}")
        return {"message": f"Synced {new_count} new transactions"}
    except Exception as e:
        logger.error(f"Failed to sync transactions: {e}")
        raise BadRequestException("Failed to sync transactions")


@router.delete("/accounts/{linked_account_id}")
async def disconnect_account(
    linked_account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Disconnect a linked account"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    linked_account_result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == linked_account_id,
            LinkedAccount.account_id == account.id
        )
    )
    linked_account = linked_account_result.scalar_one_or_none()

    if not linked_account:
        raise NotFoundException("Linked Account", str(linked_account_id))

    linked_account.is_active = False
    await db.commit()

    logger.info(f"Account disconnected: {linked_account_id}")
    return {"message": "Account disconnected successfully"}


@router.get("/accounts/{linked_account_id}")
async def get_linked_account_details(
    linked_account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific linked account"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    linked_account_result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == linked_account_id,
            LinkedAccount.account_id == account.id
        )
    )
    linked_account = linked_account_result.scalar_one_or_none()

    if not linked_account:
        raise NotFoundException("Linked Account", str(linked_account_id))

    return linked_account


async def _get_own_linked_account(db: AsyncSession, current_user: User, linked_account_id: UUID) -> LinkedAccount:
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    if not account:
        raise NotFoundException("Account", str(current_user.id))

    linked_account_result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == linked_account_id,
            LinkedAccount.account_id == account.id
        )
    )
    linked_account = linked_account_result.scalar_one_or_none()
    if not linked_account:
        raise NotFoundException("Linked Account", str(linked_account_id))
    return linked_account


@router.post("/accounts/{linked_account_id}/refresh")
async def refresh_account_balance(
    linked_account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Refresh account balance from Plaid"""
    linked_account = await _get_own_linked_account(db, current_user, linked_account_id)

    ok = await refresh_linked_account_balance(db, linked_account.id)
    if not ok:
        raise BadRequestException("Failed to refresh account balance")

    await db.refresh(linked_account)
    logger.info(f"Account balance refreshed: {linked_account_id}")
    return {
        "message": "Account balance refreshed successfully",
        "balance": float(linked_account.balance) if linked_account.balance is not None else None,
        "currency": linked_account.currency
    }


@router.get("/accounts/{linked_account_id}/holdings")
async def get_account_holdings(
    linked_account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Investment holdings for a specific linked account — securities held,
    quantity, cost basis, current value. Empty for non-investment accounts."""
    linked_account = await _get_own_linked_account(db, current_user, linked_account_id)

    result = await db.execute(
        select(InvestmentHolding, Security)
        .join(Security, InvestmentHolding.security_id == Security.id)
        .where(InvestmentHolding.linked_account_id == linked_account.id)
    )
    rows = result.all()

    return {
        "holdings": [
            {
                "id": str(holding.id),
                "ticker_symbol": security.ticker_symbol,
                "name": security.name,
                "security_type": security.security_type,
                "quantity": float(holding.quantity),
                "cost_basis": float(holding.cost_basis) if holding.cost_basis is not None else None,
                "institution_value": float(holding.institution_value),
                "institution_price": float(holding.institution_price) if holding.institution_price is not None else None,
                "currency": holding.currency,
            }
            for holding, security in rows
        ],
        "total_value": float(sum((holding.institution_value for holding, _ in rows), Decimal("0.00"))),
    }


@router.get("/accounts/{linked_account_id}/liabilities")
async def get_account_liability(
    linked_account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Liability detail (APR/statement/term data) for a credit/loan linked
    account. 404 if the account has no liability detail synced yet — the
    account's `balance` (from GET /banking/accounts) is the amount owed
    either way; this adds the detail on top of it."""
    linked_account = await _get_own_linked_account(db, current_user, linked_account_id)

    liability_result = await db.execute(
        select(Liability).where(Liability.linked_account_id == linked_account.id)
    )
    liability = liability_result.scalar_one_or_none()
    if not liability:
        raise NotFoundException("Liability detail", str(linked_account_id))

    return {
        "liability_type": liability.liability_type,
        "balance_owed": float(linked_account.balance) if linked_account.balance is not None else None,
        "last_payment_amount": float(liability.last_payment_amount) if liability.last_payment_amount is not None else None,
        "last_payment_date": liability.last_payment_date.isoformat() if liability.last_payment_date else None,
        "next_payment_due_date": liability.next_payment_due_date.isoformat() if liability.next_payment_due_date else None,
        "minimum_payment_amount": float(liability.minimum_payment_amount) if liability.minimum_payment_amount is not None else None,
        "last_statement_balance": float(liability.last_statement_balance) if liability.last_statement_balance is not None else None,
        "is_overdue": liability.is_overdue,
        "details": liability.details,
    }


@router.get("/accounts/{linked_account_id}/transactions")
async def get_account_transactions(
    linked_account_id: UUID,
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get transactions for a specific linked account"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        raise NotFoundException("Account", str(current_user.id))

    linked_account_result = await db.execute(
        select(LinkedAccount).where(
            LinkedAccount.id == linked_account_id,
            LinkedAccount.account_id == account.id
        )
    )
    linked_account = linked_account_result.scalar_one_or_none()

    if not linked_account:
        raise NotFoundException("Linked Account", str(linked_account_id))

    # Get transactions from database
    from app.models.banking import Transaction
    query = select(Transaction).where(Transaction.linked_account_id == linked_account.id)

    if start_date:
        query = query.where(Transaction.transaction_date >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.where(Transaction.transaction_date <= datetime.fromisoformat(end_date))

    result = await db.execute(query.order_by(Transaction.transaction_date.desc()).limit(limit))
    transactions = result.scalars().all()

    return {
        "transactions": [
            {
                "id": str(tx.id),
                "amount": float(tx.amount),
                "currency": tx.currency,
                "description": tx.description,
                "category": tx.category,
                "transaction_date": tx.transaction_date.isoformat(),
                "created_at": tx.created_at.isoformat()
            }
            for tx in transactions
        ],
        "count": len(transactions)
    }
