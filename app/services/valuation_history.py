"""Batched asset-valuation history lookups.

The per-asset "latest valuation before date X" query pattern turned into an
N+1 catastrophe on accounts with many assets (90 assets x 31 snapshot dates =
~2,800 sequential round-trips to Supabase — the 4-minute
/investment/performance from the Aug 2026 QA pass). Every endpoint that needs
historical values should load the account's valuations ONCE via
``load_valuations`` and answer date questions in Python with ``value_asof`` /
``first_value``.
"""
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import AssetValuation


async def load_valuations(
    db: AsyncSession, asset_ids: Sequence[UUID]
) -> Dict[UUID, List[AssetValuation]]:
    """One query: every valuation for the given assets, grouped per asset and
    sorted oldest-first (the order value_asof/first_value rely on)."""
    if not asset_ids:
        return {}
    result = await db.execute(
        select(AssetValuation)
        .where(AssetValuation.asset_id.in_(list(asset_ids)))
        .order_by(AssetValuation.valuation_date.asc())
    )
    grouped: Dict[UUID, List[AssetValuation]] = {}
    for valuation in result.scalars().all():
        grouped.setdefault(valuation.asset_id, []).append(valuation)
    return grouped


def _naive(dt: datetime) -> datetime:
    # Legacy rows may be naive while query dates are aware (or vice versa);
    # comparing the two raises TypeError, so strip tzinfo on both sides.
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def value_asof(valuations: List, asset, when: datetime) -> Decimal:
    """Latest valuation on/before ``when``; before the first valuation, the
    first one; with no history at all, the asset's current value."""
    when = _naive(when)
    chosen = None
    for valuation in valuations:  # oldest-first
        if _naive(valuation.valuation_date) <= when:
            chosen = valuation
        else:
            break
    if chosen is not None:
        return chosen.value
    if valuations:
        return valuations[0].value
    return asset.current_value


def first_value(valuations: List, asset) -> Decimal:
    """Earliest recorded valuation (cost-basis proxy), else current value."""
    if valuations:
        return valuations[0].value
    return asset.current_value
