from fastapi import APIRouter, Depends, status, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from decimal import Decimal
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account, AccountType
from app.models.kyc import KYCVerification, KYCStatus
from app.models.joint_invitation import JointAccountInvitation, InvitationStatus
from app.models.payment import Payment, PaymentStatus
from app.models.asset import Asset
from app.schemas.account import AccountCreate, AccountResponse
from app.core.exceptions import ConflictException, NotFoundException, BadRequestException, UnauthorizedException
from app.core.permissions import Role, Permission, has_permission
from app.utils.logger import logger
from app.utils.helpers import generate_reference_id
from pydantic import BaseModel
from uuid import UUID

router = APIRouter()


class AccountVerificationRequest(BaseModel):
    verification_code: Optional[str] = None


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    account_data: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create an account (Individual, Corporate, Trust, or Joint)"""
    existing_account = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    if existing_account.scalar_one_or_none():
        raise ConflictException("User already has an account")
    
    # For joint accounts, validate joint users
    if account_data.is_joint:
        if not account_data.joint_users or len(account_data.joint_users) == 0:
            raise BadRequestException("Joint accounts require at least one joint user")
        
        # Verify joint users exist (simplified - in production, validate user IDs)
        joint_user_ids = account_data.joint_users
        for user_id in joint_user_ids:
            user_result = await db.execute(
                select(User).where(User.id == user_id)
            )
            if not user_result.scalar_one_or_none():
                raise NotFoundException("User", user_id)
    
    account = Account(
        user_id=current_user.id,
        account_type=account_data.account_type,
        account_name=account_data.account_name,
        is_joint=account_data.is_joint,
        joint_users=",".join(account_data.joint_users) if account_data.joint_users else None,
        tax_id=account_data.tax_id,
    )
    
    db.add(account)
    await db.commit()
    await db.refresh(account)
    
    logger.info(f"Account created for user {current_user.id}")
    return account


@router.get("/me", response_model=AccountResponse)
async def get_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's account"""
    result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    return account


@router.put("/me", response_model=AccountResponse)
async def update_account(
    account_data: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update account information"""
    result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Update account fields
    if account_data.account_name:
        account.account_name = account_data.account_name
    if account_data.tax_id:
        account.tax_id = account_data.tax_id
    
    # Handle joint account updates
    if account_data.is_joint and account_data.joint_users:
        # Verify joint users exist
        for user_id in account_data.joint_users:
            user_result = await db.execute(
                select(User).where(User.id == user_id)
            )
            if not user_result.scalar_one_or_none():
                raise NotFoundException("User", user_id)
        
        account.is_joint = True
        account.joint_users = ",".join(account_data.joint_users)
    
    await db.commit()
    await db.refresh(account)
    
    logger.info(f"Account updated for user {current_user.id}")
    return account


@router.post("/verify", response_model=dict)
async def verify_account(
    verification_data: AccountVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Verify account (requires KYC approval)"""
    result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Check KYC status
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if not kyc:
        raise BadRequestException("KYC verification not started")
    
    if kyc.status != KYCStatus.APPROVED:
        raise BadRequestException(f"KYC status is {kyc.status.value}, must be approved")
    
    # Account is verified if KYC is approved
    return {
        "verified": True,
        "message": "Account verified successfully",
        "kyc_status": kyc.status.value
    }


@router.get("/joint-users", response_model=List[dict])
async def get_joint_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get joint account users"""
    result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    if not account.is_joint or not account.joint_users:
        return []
    
    joint_user_ids = account.joint_users.split(",")
    joint_users = []
    
    for user_id in joint_user_ids:
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            joint_users.append({
                "id": str(user.id),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
            })
    
    return joint_users


class AccountSettings(BaseModel):
    notifications: Optional[Dict[str, bool]] = None
    privacy: Optional[Dict[str, bool]] = None
    trading_preferences: Optional[Dict[str, Any]] = None


class InvitationCreate(BaseModel):
    invited_user_email: str


@router.post("/joint-users/invite", status_code=status.HTTP_201_CREATED)
async def invite_joint_user(
    invitation_data: InvitationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Invite a user to join as joint account holder"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    if not account.is_joint:
        raise BadRequestException("Account must be a joint account")
    
    # Find user by email
    user_result = await db.execute(
        select(User).where(User.email == invitation_data.invited_user_email)
    )
    invited_user = user_result.scalar_one_or_none()
    
    if not invited_user:
        raise NotFoundException("User", invitation_data.invited_user_email)
    
    if invited_user.id == current_user.id:
        raise BadRequestException("Cannot invite yourself")
    
    # Check if user already has an account
    invited_account_result = await db.execute(
        select(Account).where(Account.user_id == invited_user.id)
    )
    if invited_account_result.scalar_one_or_none():
        raise BadRequestException("User already has an account")
    
    # Check if already invited
    existing_invitation = await db.execute(
        select(JointAccountInvitation).where(
            JointAccountInvitation.account_id == account.id,
            JointAccountInvitation.invited_user_id == invited_user.id,
            JointAccountInvitation.status == InvitationStatus.PENDING
        )
    )
    if existing_invitation.scalar_one_or_none():
        raise BadRequestException("Invitation already sent")
    
    # Generate invitation token
    token = generate_reference_id("INV")
    
    invitation = JointAccountInvitation(
        account_id=account.id,
        invited_user_id=invited_user.id,
        invited_by_user_id=current_user.id,
        token=token,
        status=InvitationStatus.PENDING,
        expires_at=datetime.utcnow() + timedelta(days=7)
    )
    
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    
    # TODO: Send invitation email
    
    logger.info(f"Joint account invitation sent: {invitation.id}")
    return {
        "message": "Invitation sent successfully",
        "invitation_id": invitation.id,
        "token": token
    }


@router.post("/joint-users/accept-invitation")
async def accept_invitation(
    token: str = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Accept joint account invitation"""
    invitation_result = await db.execute(
        select(JointAccountInvitation).where(
            JointAccountInvitation.token == token,
            JointAccountInvitation.invited_user_id == current_user.id
        )
    )
    invitation = invitation_result.scalar_one_or_none()
    
    if not invitation:
        raise NotFoundException("Invitation", token)
    
    if invitation.status != InvitationStatus.PENDING:
        raise BadRequestException("Invitation already processed")
    
    if invitation.expires_at < datetime.utcnow():
        invitation.status = InvitationStatus.EXPIRED
        await db.commit()
        raise BadRequestException("Invitation has expired")
    
    # Add user to joint account
    account_result = await db.execute(
        select(Account).where(Account.id == invitation.account_id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(invitation.account_id))
    
    # Add to joint_users string
    joint_users_list = account.joint_users.split(",") if account.joint_users else []
    if str(current_user.id) not in joint_users_list:
        joint_users_list.append(str(current_user.id))
        account.joint_users = ",".join(joint_users_list)
        account.is_joint = True
    
    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_at = datetime.utcnow()
    
    await db.commit()
    
    logger.info(f"Invitation accepted: {invitation.id}")
    return {"message": "Invitation accepted successfully"}


@router.delete("/joint-users/{user_id}")
async def remove_joint_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove joint user from account"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    if not account.is_joint or not account.joint_users:
        raise BadRequestException("Account is not a joint account")
    
    if str(user_id) == str(current_user.id):
        raise BadRequestException("Cannot remove yourself")
    
    joint_users_list = account.joint_users.split(",")
    if str(user_id) not in joint_users_list:
        raise NotFoundException("Joint User", str(user_id))
    
    # Check for active transactions (simplified check)
    # In production, check for active marketplace listings, pending payments, etc.
    
    joint_users_list.remove(str(user_id))
    if joint_users_list:
        account.joint_users = ",".join(joint_users_list)
    else:
        account.joint_users = None
        account.is_joint = False
    
    await db.commit()
    
    logger.info(f"Joint user removed: {user_id} from account {account.id}")
    return {"message": "Joint user removed successfully"}


@router.get("/settings")
async def get_account_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get account settings"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Return default settings (in production, store in database)
    return {
        "notifications": {
            "email": True,
            "sms": False,
            "push": True
        },
        "privacy": {
            "profile_visible": True,
            "portfolio_visible": False
        },
        "trading_preferences": {
            "default_order_type": "market",
            "confirm_before_trade": True
        }
    }


@router.put("/settings")
async def update_account_settings(
    settings: AccountSettings,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update account settings"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # In production, store settings in database (JSONB field)
    # For now, just return success
    logger.info(f"Account settings updated for user {current_user.id}")
    return {"message": "Settings updated successfully"}


@router.get("/stats")
async def get_account_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get account statistics"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Account age
    account_age_days = (datetime.utcnow() - account.created_at).days
    
    # Total transactions
    transactions_result = await db.execute(
        select(func.count(Payment.id)).where(
            Payment.account_id == account.id,
            Payment.status == PaymentStatus.COMPLETED
        )
    )
    total_transactions = transactions_result.scalar() or 0
    
    # Portfolio value
    assets_result = await db.execute(
        select(func.sum(Asset.current_value)).where(Asset.account_id == account.id)
    )
    portfolio_value = assets_result.scalar() or Decimal("0")
    
    # KYC status
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    kyc_status = kyc.status.value if kyc else "not_started"
    
    # Subscription status
    from app.models.payment import Subscription
    subscription_result = await db.execute(
        select(Subscription).where(Subscription.account_id == account.id)
    )
    subscription = subscription_result.scalar_one_or_none()
    subscription_status = subscription.status.value if subscription else "none"
    
    return {
        "account_age_days": account_age_days,
        "total_transactions": total_transactions,
        "portfolio_value": float(portfolio_value),
        "kyc_status": kyc_status,
        "subscription_status": subscription_status,
        "is_verified": current_user.is_verified,
        "is_joint": account.is_joint
    }


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete account (soft delete)"""
    account_result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(current_user.id))
    
    # Check for active subscriptions
    from app.models.payment import Subscription, SubscriptionStatus
    subscription_result = await db.execute(
        select(Subscription).where(
            Subscription.account_id == account.id,
            Subscription.status == SubscriptionStatus.ACTIVE
        )
    )
    if subscription_result.scalar_one_or_none():
        raise BadRequestException("Cannot delete account with active subscription. Please cancel subscription first.")
    
    # Check for active marketplace listings
    from app.models.marketplace import MarketplaceListing, ListingStatus
    listing_result = await db.execute(
        select(MarketplaceListing).where(
            MarketplaceListing.account_id == account.id,
            MarketplaceListing.status.in_([ListingStatus.ACTIVE, ListingStatus.PENDING_APPROVAL])
        )
    )
    if listing_result.scalar_one_or_none():
        raise BadRequestException("Cannot delete account with active marketplace listings")
    
    # Soft delete: Deactivate user account
    current_user.is_active = False
    # In production, add deleted_at timestamp and anonymize PII
    
    await db.commit()
    
    logger.info(f"Account deleted (soft): {account.id}")
    return None


@router.post("/admin/{account_id}/suspend")
async def suspend_account(
    account_id: UUID,
    reason: str = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Suspend account (admin only)"""
    if not has_permission(current_user.role, Permission.MANAGE_USERS):
        raise UnauthorizedException("Insufficient permissions")
    
    account_result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(account_id))
    
    account.user.is_active = False
    # In production, add suspended_at and suspended_reason fields
    
    await db.commit()
    
    logger.info(f"Account suspended: {account_id} by {current_user.id}")
    return {"message": "Account suspended successfully", "reason": reason}


@router.post("/admin/{account_id}/activate")
async def activate_account(
    account_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Activate account (admin only)"""
    if not has_permission(current_user.role, Permission.MANAGE_USERS):
        raise UnauthorizedException("Insufficient permissions")
    
    account_result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    account = account_result.scalar_one_or_none()
    
    if not account:
        raise NotFoundException("Account", str(account_id))
    
    # Check KYC status
    kyc_result = await db.execute(
        select(KYCVerification).where(KYCVerification.account_id == account.id)
    )
    kyc = kyc_result.scalar_one_or_none()
    
    if kyc and kyc.status == KYCStatus.APPROVED:
        account.user.is_active = True
        account.user.is_verified = True
    else:
        account.user.is_active = True
    
    await db.commit()
    
    logger.info(f"Account activated: {account_id} by {current_user.id}")
    return {"message": "Account activated successfully"}
