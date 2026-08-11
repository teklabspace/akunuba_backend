"""Seed the four platform investment strategies (idempotent).

IDs are deterministic (uuid5 of a fixed namespace string) so every
environment gets the SAME ids — the frontend's static export whitelists
strategy detail pages by id (`generateStaticParams`), so those ids must be
stable. Run: ./.venv/Scripts/python.exe scripts/seed_strategies.py
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.investment_strategy import InvestmentStrategy


def strategy_id(slug: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"akunuba:strategy:{slug}")


STRATEGIES = [
    {
        "slug": "growth-momentum",
        "title": "Growth Momentum",
        "description": "Ride sector momentum with monthly rebalancing into the strongest performers.",
        "full_description": (
            "A momentum strategy that ranks large-cap equities by 6-month relative strength "
            "and rotates monthly into the top decile. Positions are equal-weighted and "
            "rebalanced on the first trading day of each month; a 200-day moving-average "
            "market filter moves the portfolio to cash in sustained downtrends."
        ),
        "author": "Akunuba Research",
        "chart_type": "line",
        "parameters": {"lookback_months": 6, "rebalance": "monthly", "positions": 10, "market_filter": "SMA200"},
        "is_open_source": True,
    },
    {
        "slug": "value-dividend",
        "title": "Value Dividend Income",
        "description": "Quality dividend payers screened for valuation and payout safety.",
        "full_description": (
            "Screens for companies with 10+ years of dividend growth, payout ratios under "
            "60% and free-cash-flow yields above the sector median, then weights by inverse "
            "volatility. Designed for income with lower drawdowns than the broad market; "
            "rebalanced quarterly."
        ),
        "author": "Akunuba Research",
        "chart_type": "area",
        "parameters": {"min_dividend_years": 10, "max_payout_ratio": 0.6, "rebalance": "quarterly"},
        "is_open_source": True,
    },
    {
        "slug": "crypto-dca",
        "title": "Crypto DCA Core",
        "description": "Disciplined dollar-cost averaging into BTC and ETH with volatility bands.",
        "full_description": (
            "Automates a fixed weekly buy split 70/30 between BTC and ETH. Contributions "
            "scale up to 1.5x when price sits below the 30-week average and down to 0.5x "
            "when more than two standard deviations above it. No leverage, cold-storage "
            "settlement assumed."
        ),
        "author": "Akunuba Research",
        "chart_type": "candlestick",
        "parameters": {"assets": {"BTC": 0.7, "ETH": 0.3}, "cadence": "weekly", "volatility_bands": True},
        "is_open_source": False,
    },
    {
        "slug": "balanced-6040",
        "title": "Balanced 60/40 Plus",
        "description": "Classic 60/40 core with a 10% alternatives sleeve for inflation protection.",
        "full_description": (
            "A strategic allocation of 55% global equities, 35% investment-grade bonds and "
            "10% alternatives (gold and broad commodities). Annual rebalancing with 5% "
            "drift bands; the alternatives sleeve is the inflation hedge the plain 60/40 "
            "lacks."
        ),
        "author": "Akunuba Research",
        "chart_type": "pie",
        "parameters": {"equities": 0.55, "bonds": 0.35, "alternatives": 0.10, "rebalance": "annual"},
        "is_open_source": False,
    },
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        for spec in STRATEGIES:
            sid = strategy_id(spec["slug"])
            existing = (
                await db.execute(select(InvestmentStrategy).where(InvestmentStrategy.id == sid))
            ).scalar_one_or_none()
            if existing:
                print(f"exists  {sid}  {spec['title']}")
                continue
            db.add(
                InvestmentStrategy(
                    id=sid,
                    account_id=None,
                    title=spec["title"],
                    description=spec["description"],
                    full_description=spec["full_description"],
                    author=spec["author"],
                    chart_type=spec["chart_type"],
                    parameters=spec["parameters"],
                    is_open_source=spec["is_open_source"],
                )
            )
            print(f"created {sid}  {spec['title']}")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
