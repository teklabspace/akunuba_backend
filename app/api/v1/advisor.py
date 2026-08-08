from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, Any
from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.kyc import KYCVerification
from app.models.advisor_client import AdvisorClient
from app.models.payment import Subscription
from app.core.permissions import Role
from app.core.exceptions import ForbiddenException

router = APIRouter()


@router.get("/clients", response_model=Dict[str, Any])
async def list_my_clients(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The advisor's assigned investors (clients), with KYC status, plan, and the
    conversation_id of their auto-created chat."""
    if current_user.role not in (Role.ADVISOR, Role.ADMIN):
        raise ForbiddenException("Only advisors can view their client list.")

    from app.api.v1.subscriptions import get_plan_tier

    rows = (await db.execute(
        select(AdvisorClient, User)
        .join(User, AdvisorClient.client_id == User.id)
        .where(AdvisorClient.advisor_id == current_user.id)
        .order_by(AdvisorClient.created_at.desc())
    )).all()

    data = []
    for ac, client in rows:
        account = (await db.execute(
            select(Account).where(Account.user_id == client.id)
        )).scalar_one_or_none()

        kyc_status = None
        plan = None
        if account:
            kyc = (await db.execute(
                select(KYCVerification).where(KYCVerification.account_id == account.id)
            )).scalar_one_or_none()
            kyc_status = kyc.status.value if kyc else "not_started"
            sub = (await db.execute(
                select(Subscription).where(Subscription.account_id == account.id)
            )).scalar_one_or_none()
            plan = get_plan_tier(sub) if sub else None

        data.append({
            "client_id": str(client.id),
            "name": f"{client.first_name or ''} {client.last_name or ''}".strip() or client.email,
            "email": client.email,
            "kyc_status": kyc_status,
            "plan": plan,
            "conversation_id": str(ac.conversation_id) if ac.conversation_id else None,
        })

    return {"data": data, "total": len(data)}


@router.get("/book", response_model=Dict[str, Any])
async def my_book(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated portfolio view of the advisor's book for the dashboard
    charts: per-client totals with their asset-class split, plus the combined
    class allocation. Core (owned) assets only — same scope as
    /portfolio/allocation."""
    if current_user.role not in (Role.ADVISOR, Role.ADMIN):
        raise ForbiddenException("Only advisors can view their book.")

    from app.models.asset import Asset
    from app.services.net_worth import core_assets

    rows = (await db.execute(
        select(AdvisorClient, User)
        .join(User, AdvisorClient.client_id == User.id)
        .where(AdvisorClient.advisor_id == current_user.id)
        .order_by(AdvisorClient.created_at.desc())
    )).all()

    clients = []
    allocation_by_type: Dict[str, Dict[str, Any]] = {}
    book_total = 0.0

    for _, client in rows:
        account = (await db.execute(
            select(Account).where(Account.user_id == client.id)
        )).scalar_one_or_none()

        class_values: Dict[str, float] = {}
        if account:
            assets = core_assets((await db.execute(
                select(Asset).where(Asset.account_id == account.id)
            )).scalars().all())
            for asset in assets:
                asset_type = asset.asset_type.value if asset.asset_type else "other"
                value = float(asset.current_value or 0)
                class_values[asset_type] = class_values.get(asset_type, 0.0) + value
                bucket = allocation_by_type.setdefault(
                    asset_type, {"value": 0.0, "count": 0}
                )
                bucket["value"] += value
                bucket["count"] += 1

        client_total = sum(class_values.values())
        book_total += client_total
        clients.append({
            "client_id": str(client.id),
            "name": f"{client.first_name or ''} {client.last_name or ''}".strip() or client.email,
            "total_value": client_total,
            "classes": [
                {"asset_type": t, "value": v}
                for t, v in sorted(class_values.items(), key=lambda kv: -kv[1])
            ],
        })

    clients.sort(key=lambda c: -c["total_value"])
    allocation = [
        {"asset_type": t, "value": d["value"], "count": d["count"]}
        for t, d in sorted(allocation_by_type.items(), key=lambda kv: -kv[1]["value"])
    ]
    return {
        "data": {
            "total_value": book_total,
            "client_count": len(clients),
            "clients": clients,
            "allocation": allocation,
        }
    }
