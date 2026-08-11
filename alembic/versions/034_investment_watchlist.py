"""Investment watchlist table.

The table was created directly in the shared Supabase during the 9-11 Aug
2026 QA pass (via Base.metadata.create_all), so every statement is guarded to
no-op there while still building fresh environments correctly.

The watchlist model's asset_type column reuses the shared ``assettype`` enum
(both Python enum classes are named AssetType, so SQLAlchemy maps them to the
same PG type). The watchlist accepts "etf", which the shared enum lacked —
add it here so watchlist inserts with ETF don't blow up.

Revision ID: 034_investment_watchlist
Revises: 033_escrow_payout_fields
"""
from alembic import op

revision = "034_investment_watchlist"
down_revision = "033_escrow_payout_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE assettype ADD VALUE IF NOT EXISTS 'ETF'")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS investment_watchlist (
            id UUID PRIMARY KEY,
            account_id UUID NOT NULL REFERENCES accounts(id),
            symbol VARCHAR(50) NOT NULL,
            name VARCHAR(255),
            asset_type assettype NOT NULL,
            added_at TIMESTAMP WITH TIME ZONE DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_investment_watchlist_account_id "
        "ON investment_watchlist (account_id)"
    )


def downgrade() -> None:
    # The 'ETF' enum value is left in place: PG cannot drop enum values.
    op.execute("DROP TABLE IF EXISTS investment_watchlist")
