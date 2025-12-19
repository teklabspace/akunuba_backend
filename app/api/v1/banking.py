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
from app.integrations.plaid_client import PlaidClient
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException
from app.api.deps import get_account, get_user_subscription_plan
from app.core.features import Feature, has_feature
from app.utils.logger import logger
from uuid import UUID
from pydantic import BaseModel

router = APIRouter()


class LinkTokenResponse(BaseModel):
    link_token: str


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
    """Create Plaid link token for account linking"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    try:
        link_token = PlaidClient.create_link_token(
            user_id=str(current_user.id),
            account_id=str(account.id)
        )
        return LinkTokenResponse(link_token=link_token)
    except Exception as e:
        logger.error(f"Failed to create Plaid link token: {e}")
        raise BadRequestException("Failed to create link token")


@router.post("/link")
async def link_account(
    public_token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Link bank account using Plaid public token"""
    account = await get_account(current_user=current_user, db=db)
    plan = await get_user_subscription_plan(account=account, db=db)
    
    # Check subscription feature
    if not has_feature(plan, Feature.BANKING):
        raise ForbiddenException("Banking integration requires Annual subscription")
    
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
        
        # Create linked account records
        linked_accounts = []
        for acc_data in accounts_data:
            linked_account = LinkedAccount(
                account_id=account.id,
                plaid_item_id=item_id,
                plaid_access_token=access_token,
                account_type=AccountType.BANKING,  # Default, could be determined from account type
                institution_name=acc_data.get("name", "Unknown"),
                account_name=acc_data.get("name", "Account"),
                account_number=acc_data.get("mask", ""),
                balance=Decimal(str(acc_data.get("balances", {}).get("available", 0))),
                currency="USD",
                last_synced_at=datetime.utcnow(),
            )
            db.add(linked_account)
            linked_accounts.append(linked_account)
        
        await db.commit()
        
        logger.info(f"Accounts linked for user {current_user.id}")
        return {"message": f"{len(linked_accounts)} account(s) linked successfully"}
    except Exception as e:
        logger.error(f"Failed to link account: {e}")
        raise BadRequestException("Failed to link account")


@router.get("/accounts", response_model=List[LinkedAccountResponse])
async def get_linked_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all linked accounts"""
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
    
    return linked_accounts


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
        
        logger.info(f"Synced {new_count} transactions for account {linked_account_id}")
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


@router.post("/accounts/{linked_account_id}/refresh")
async def refresh_account_balance(
    linked_account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Refresh account balance from Plaid"""
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
        # Get updated account information from Plaid
        accounts_response = PlaidClient.get_accounts(linked_account.plaid_access_token)
        accounts_data = accounts_response.get("accounts", [])
        
        # Find matching account
        updated_account = None
        for acc_data in accounts_data:
            if acc_data.get("mask") == linked_account.account_number or acc_data.get("account_id") == linked_account.plaid_item_id:
                updated_account = acc_data
                break
        
        if updated_account:
            linked_account.balance = Decimal(str(updated_account.get("balances", {}).get("available", 0)))
            linked_account.last_synced_at = datetime.utcnow()
            await db.commit()
            
            logger.info(f"Account balance refreshed: {linked_account_id}")
            return {
                "message": "Account balance refreshed successfully",
                "balance": float(linked_account.balance),
                "currency": linked_account.currency
            }
        else:
            raise BadRequestException("Account not found in Plaid")
    except Exception as e:
        logger.error(f"Failed to refresh account balance: {e}")
        raise BadRequestException("Failed to refresh account balance")


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

