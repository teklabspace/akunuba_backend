from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from app.models.account import AccountType


class AccountCreate(BaseModel):
    account_type: AccountType
    account_name: str
    is_joint: bool = False
    joint_users: Optional[List[str]] = None
    tax_id: Optional[str] = None


class AccountResponse(BaseModel):
    id: UUID
    account_type: AccountType
    account_name: str
    is_joint: bool
    joint_users: Optional[str] = None
    tax_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

