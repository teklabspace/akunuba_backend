"""Investment goals table (Goals Tracker backend — QA finding B1).

Revision ID: 035_investment_goals
Revises: 034_investment_watchlist
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, UUID

revision = "035_investment_goals"
down_revision = "034_investment_watchlist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE goalstatus AS ENUM ('ACTIVE', 'COMPLETED', 'CANCELLED');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        """
    )
    op.create_table(
        "investment_goals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=True),
        sa.Column("target_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("target_quantity", sa.Numeric(20, 8), nullable=True),
        sa.Column("current_value", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("current_quantity", sa.Numeric(20, 8), nullable=True, server_default="0"),
        sa.Column("monthly_contribution", sa.Numeric(20, 2), nullable=True),
        sa.Column("risk_tolerance", sa.String(20), nullable=True),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column(
            "status",
            ENUM("ACTIVE", "COMPLETED", "CANCELLED", name="goalstatus", create_type=False),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_investment_goals_account_id", "investment_goals", ["account_id"])


def downgrade() -> None:
    op.drop_table("investment_goals")
    op.execute("DROP TYPE IF EXISTS goalstatus")
