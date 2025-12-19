from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.account import Account, AccountType
from app.models.kyb import KYBVerification, KYBStatus
from app.core.exceptions import ForbiddenException
from app.utils.logger import logger


class AccountRestrictionsService:
    @staticmethod
    async def check_kyb_required(db: AsyncSession, account: Account) -> bool:
        """Check if account requires KYB verification"""
        return account.account_type in [AccountType.CORPORATE, AccountType.TRUST]
    
    @staticmethod
    async def is_kyb_verified(db: AsyncSession, account: Account) -> bool:
        """Check if corporate/trust account has completed KYB"""
        if account.account_type not in [AccountType.CORPORATE, AccountType.TRUST]:
            return True  # Individual accounts don't need KYB
        
        result = await db.execute(
            select(KYBVerification).where(KYBVerification.account_id == account.id)
        )
        kyb = result.scalar_one_or_none()
        
        if not kyb:
            return False
        
        return kyb.status == KYBStatus.APPROVED
    
    @staticmethod
    async def require_kyb_verification(db: AsyncSession, account: Account, action: str):
        """Require KYB verification for an action"""
        if await AccountRestrictionsService.check_kyb_required(db, account):
            if not await AccountRestrictionsService.is_kyb_verified(db, account):
                raise ForbiddenException(
                    f"KYB verification required for {account.account_type.value} accounts to {action}. "
                    "Please complete KYB verification first."
                )
    
    @staticmethod
    async def get_blocked_actions(db: AsyncSession, account: Account) -> list:
        """Get list of actions blocked for account"""
        blocked = []
        
        if await AccountRestrictionsService.check_kyb_required(db, account):
            if not await AccountRestrictionsService.is_kyb_verified(db, account):
                blocked = [
                    "create_marketplace_listings",
                    "create_escrow_transactions",
                    "create_trading_orders",
                    "link_bank_accounts",
                    "activate_premium_subscription"
                ]
        
        return blocked

