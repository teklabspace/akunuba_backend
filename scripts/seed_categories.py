"""
Seed all asset categories into the asset_categories table.

Run from project root:
    python -m scripts.seed_categories
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all models so SQLAlchemy relationship resolution succeeds
import app.models  # noqa: F401

from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.asset import AssetCategory, CategoryGroup


# ---------------------------------------------------------------------------
# Form fields and card fields per group
# ---------------------------------------------------------------------------

ASSETS_FORM_FIELDS = [
    "name", "category", "category_group", "description",
    "location", "current_value", "estimated_value", "currency",
    "condition", "ownership_type", "acquisition_date", "purchase_price",
    "valuation_type", "specifications", "photos", "documents",
]

ASSETS_CARD_FIELDS = [
    "name", "category", "current_value", "currency",
    "condition", "location", "image", "status",
]

PORTFOLIO_FORM_FIELDS = [
    "name", "category", "category_group", "description",
    "current_value", "estimated_value", "currency",
    "acquisition_date", "purchase_price", "valuation_type",
    "specifications.institution", "specifications.risk_level",
    "specifications.investment_type", "specifications.account_number_masked",
    "specifications.investment_horizon", "photos", "documents",
]

PORTFOLIO_CARD_FIELDS = [
    "name", "category", "current_value", "currency",
    "specifications.institution", "specifications.risk_level", "status",
]

LIABILITIES_FORM_FIELDS = [
    "name", "category", "category_group", "description",
    "current_value", "currency",
    "specifications.creditor", "specifications.interest_rate",
    "specifications.maturity_date", "specifications.monthly_payment",
    "specifications.account_number_masked", "documents",
]

LIABILITIES_CARD_FIELDS = [
    "name", "category", "current_value", "currency",
    "specifications.creditor", "specifications.interest_rate",
    "specifications.maturity_date", "status",
]

SHADOW_WEALTH_FORM_FIELDS = [
    "name", "category", "category_group", "description",
    "estimated_value", "currency",
    "specifications.source", "specifications.expected_date",
    "specifications.vesting_schedule", "specifications.conditions",
    "documents",
]

SHADOW_WEALTH_CARD_FIELDS = [
    "name", "category", "estimated_value", "currency",
    "specifications.source", "specifications.expected_date", "status",
]


# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

CATEGORIES = [
    # ── Assets ──────────────────────────────────────────────────────────────
    ("Yachts",                   CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Private Jets",             CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Real Estate",              CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Vehicles",                 CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Art & Collectibles",       CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Watches & Jewelry",        CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Precious Metals",          CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Wine & Whiskey",           CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Luxury Furniture",         CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Antiques",                 CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Fine Instruments",         CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Luxury Memorabilia",       CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Farmland & Agri Land",     CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Private Company Equity",   CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Intellectual Property",    CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Racehorses & Animals",     CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Fractional Ownerships",    CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Classic Motorcycles",      CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Green Assets",             CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Digital Collectibles",     CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Couture & Designer Wear",  CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Boats & Watercraft",       CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Raw Precious Stones",      CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),
    ("Vaulted/Stored Assets",    CategoryGroup.ASSETS,        ASSETS_FORM_FIELDS, ASSETS_CARD_FIELDS),

    # ── Portfolio ────────────────────────────────────────────────────────────
    ("Crypto Assets",                    CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Cash Flow Accounts",               CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Trade Engine",                     CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Public Equities",                  CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Fixed Income",                     CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("ETFs & Index Funds",               CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Mutual Funds",                     CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Private Equity",                   CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Hedge Funds",                      CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Commodities",                      CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Structured Products",              CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Foreign Currency",                 CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Offshore Accounts",                CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("REITs & Real Estate Funds",        CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Annuities",                        CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Investment-Linked Insurance",      CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Pension & Retirement",             CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Crowdfunding Investments",         CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Digital Assets (Non-Crypto)",      CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("ESG & Carbon Credits",             CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Margin & Credit",                  CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Royalty Streams",                  CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Litigation Finance",               CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Precious Metal ETFs",              CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Derivatives & Options",            CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Trusts / Foundations",             CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Cash Management",                  CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Stablecoins & CBDCs",              CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("DeFi Instruments",                 CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Convertible Notes",                CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Tax-Deferred Investments",         CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Stock Options / RSUs",             CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),
    ("Micro-Investments",                CategoryGroup.PORTFOLIO, PORTFOLIO_FORM_FIELDS, PORTFOLIO_CARD_FIELDS),

    # ── Liabilities ──────────────────────────────────────────────────────────
    ("Mortgages",          CategoryGroup.LIABILITIES, LIABILITIES_FORM_FIELDS, LIABILITIES_CARD_FIELDS),
    ("Personal Loans",     CategoryGroup.LIABILITIES, LIABILITIES_FORM_FIELDS, LIABILITIES_CARD_FIELDS),
    ("Business Loans",     CategoryGroup.LIABILITIES, LIABILITIES_FORM_FIELDS, LIABILITIES_CARD_FIELDS),
    ("Credit Cards",       CategoryGroup.LIABILITIES, LIABILITIES_FORM_FIELDS, LIABILITIES_CARD_FIELDS),
    ("Auto / Yacht Loans", CategoryGroup.LIABILITIES, LIABILITIES_FORM_FIELDS, LIABILITIES_CARD_FIELDS),
    ("Margin Loans",       CategoryGroup.LIABILITIES, LIABILITIES_FORM_FIELDS, LIABILITIES_CARD_FIELDS),
    ("Lines of Credit",    CategoryGroup.LIABILITIES, LIABILITIES_FORM_FIELDS, LIABILITIES_CARD_FIELDS),
    ("Tax Liabilities",    CategoryGroup.LIABILITIES, LIABILITIES_FORM_FIELDS, LIABILITIES_CARD_FIELDS),
    ("Deferred Payments",  CategoryGroup.LIABILITIES, LIABILITIES_FORM_FIELDS, LIABILITIES_CARD_FIELDS),
    ("Lease Agreements",   CategoryGroup.LIABILITIES, LIABILITIES_FORM_FIELDS, LIABILITIES_CARD_FIELDS),

    # ── Shadow Wealth ────────────────────────────────────────────────────────
    ("Pending Inheritance",     CategoryGroup.SHADOW_WEALTH, SHADOW_WEALTH_FORM_FIELDS, SHADOW_WEALTH_CARD_FIELDS),
    ("Unvested Stock / RSUs",   CategoryGroup.SHADOW_WEALTH, SHADOW_WEALTH_FORM_FIELDS, SHADOW_WEALTH_CARD_FIELDS),
    ("Deferred Compensation",   CategoryGroup.SHADOW_WEALTH, SHADOW_WEALTH_FORM_FIELDS, SHADOW_WEALTH_CARD_FIELDS),
]


async def seed():
    async with AsyncSessionLocal() as db:
        existing_result = await db.execute(select(AssetCategory.name))
        existing_names = {row[0] for row in existing_result.fetchall()}

        inserted = 0
        skipped = 0

        for name, group, form_fields, card_fields in CATEGORIES:
            if name in existing_names:
                skipped += 1
                continue

            category = AssetCategory(
                name=name,
                category_group=group,
                form_fields=form_fields,
                card_fields=card_fields,
                is_active=True,
            )
            db.add(category)
            inserted += 1
            print(f"  + {name}  ({group.value})")

        await db.commit()
        print(f"\nDone. Inserted: {inserted}  |  Already existed: {skipped}")


if __name__ == "__main__":
    asyncio.run(seed())
