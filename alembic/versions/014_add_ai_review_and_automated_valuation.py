"""Add AI asset review table/columns and 'automated' valuation type

Revision ID: 014_add_ai_review_and_automated_valuation
Revises: 013_add_referral_tables
Create Date: 2026-06-23

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "014_add_ai_review"
down_revision = "013_add_referral_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add 'automated' to the existing valuationtype enum (used by AI appraisals).
    #    On PostgreSQL 12+ ADD VALUE runs inside a transaction as long as the new
    #    value isn't used in the same transaction (it isn't here).
    op.execute("ALTER TYPE valuationtype ADD VALUE IF NOT EXISTS 'automated'")

    # 2. New enum for AI review decisions.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE aireviewstatus AS ENUM
                ('not_reviewed', 'approved', 'rejected', 'needs_review');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )

    # 3. Advisory AI review state on the asset itself.
    op.execute(
        "ALTER TABLE assets ADD COLUMN IF NOT EXISTS ai_review_status aireviewstatus "
        "NOT NULL DEFAULT 'not_reviewed'"
    )
    op.add_column(
        "assets",
        sa.Column("ai_reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 4. Append-only log of AI reviews.
    aireviewstatus = postgresql.ENUM(
        "not_reviewed", "approved", "rejected", "needs_review",
        name="aireviewstatus",
        create_type=False,  # created above
    )
    op.create_table(
        "asset_ai_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id"),
            nullable=False,
        ),
        sa.Column("decision", aireviewstatus, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("flags", postgresql.JSONB(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.execute("ALTER TABLE asset_ai_reviews ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    op.drop_table("asset_ai_reviews")
    op.drop_column("assets", "ai_reviewed_at")
    op.execute("ALTER TABLE assets DROP COLUMN IF EXISTS ai_review_status")
    op.execute("DROP TYPE IF EXISTS aireviewstatus")
    # Note: the 'automated' value added to valuationtype is left in place —
    # PostgreSQL does not support removing a value from an enum type.
