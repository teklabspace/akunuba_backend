"""Extend AI appraisal: new statuses + ai_data column on asset_appraisals

Revision ID: 015_extend_ai_appraisal
Revises: 014_add_ai_review
Create Date: 2026-06-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "015_extend_ai_appraisal"
down_revision = "014_add_ai_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add four new values to the appraisalstatus enum.
    #    PostgreSQL 12+ supports ADD VALUE inside a transaction as long as the
    #    new value is not used in the same transaction (it isn't here).
    op.execute("ALTER TYPE appraisalstatus ADD VALUE IF NOT EXISTS 'ai_appraised'")
    op.execute("ALTER TYPE appraisalstatus ADD VALUE IF NOT EXISTS 'needs_more_information'")
    op.execute("ALTER TYPE appraisalstatus ADD VALUE IF NOT EXISTS 'professional_appraisal_recommended'")
    op.execute("ALTER TYPE appraisalstatus ADD VALUE IF NOT EXISTS 'appraisal_failed'")

    # 2. Add ai_data JSONB column to asset_appraisals for storing the full
    #    extended AI response (all Section-10 fields).
    op.add_column(
        "asset_appraisals",
        sa.Column("ai_data", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("asset_appraisals", "ai_data")
    # PostgreSQL does not support removing enum values — leave them in place.
