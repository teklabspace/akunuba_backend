"""Shareable links for portfolio views (crypto portfolio "Generate link").

Revision ID: 041_portfolio_shares
Revises: 040_trading_cash_ledger
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "041_portfolio_shares"
down_revision = "040_trading_cash_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_shares",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("view", sa.String(32), nullable=False, server_default="crypto"),
        sa.Column("share_link", sa.String(500), nullable=False, unique=True),
        sa.Column("access_code", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window", JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_portfolio_shares_account_id", "portfolio_shares", ["account_id"])
    # The resolve endpoint looks the row up by code alone.
    op.create_index("ix_portfolio_shares_access_code", "portfolio_shares", ["access_code"])


def downgrade() -> None:
    op.drop_index("ix_portfolio_shares_access_code", table_name="portfolio_shares")
    op.drop_index("ix_portfolio_shares_account_id", table_name="portfolio_shares")
    op.drop_table("portfolio_shares")
