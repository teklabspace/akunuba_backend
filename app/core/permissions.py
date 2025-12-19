from enum import Enum
from typing import List


class Role(str, Enum):
    ADMIN = "admin"
    INVESTOR = "investor"
    ADVISOR = "advisor"


class Permission(str, Enum):
    READ_USERS = "read:users"
    WRITE_USERS = "write:users"
    READ_ASSETS = "read:assets"
    WRITE_ASSETS = "write:assets"
    READ_PORTFOLIO = "read:portfolio"
    WRITE_PORTFOLIO = "write:portfolio"
    TRADE = "trade"
    CREATE_LISTINGS = "create:listings"
    APPROVE_LISTINGS = "approve:listings"
    MANAGE_SUBSCRIPTIONS = "manage:subscriptions"
    VIEW_ANALYTICS = "view:analytics"
    MANAGE_SUPPORT = "manage:support"


ROLE_PERMISSIONS = {
    Role.ADMIN: [
        Permission.READ_USERS,
        Permission.WRITE_USERS,
        Permission.READ_ASSETS,
        Permission.WRITE_ASSETS,
        Permission.READ_PORTFOLIO,
        Permission.WRITE_PORTFOLIO,
        Permission.TRADE,
        Permission.CREATE_LISTINGS,
        Permission.APPROVE_LISTINGS,
        Permission.MANAGE_SUBSCRIPTIONS,
        Permission.VIEW_ANALYTICS,
        Permission.MANAGE_SUPPORT,
    ],
    Role.INVESTOR: [
        Permission.READ_USERS,
        Permission.READ_ASSETS,
        Permission.READ_PORTFOLIO,
        Permission.WRITE_PORTFOLIO,
        Permission.TRADE,
        Permission.CREATE_LISTINGS,
    ],
    Role.ADVISOR: [
        Permission.READ_USERS,
        Permission.READ_ASSETS,
        Permission.READ_PORTFOLIO,
        Permission.WRITE_PORTFOLIO,
        Permission.TRADE,
        Permission.VIEW_ANALYTICS,
        Permission.MANAGE_SUPPORT,
    ],
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, [])


def get_role_permissions(role: Role) -> List[Permission]:
    return ROLE_PERMISSIONS.get(role, [])

