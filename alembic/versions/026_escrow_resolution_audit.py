"""Add admin resolution audit columns to escrow_transactions.

Supports admin force-release / force-refund (and dispute resolution) by recording
who acted (resolved_by -> users.id) and why (resolution_reason).

Revision ID: 026_escrow_resolution_audit
Revises: 025_backfill_asset_categories
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "026_escrow_resolution_audit"
down_revision = "025_backfill_asset_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "escrow_transactions",
        sa.Column("resolved_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "escrow_transactions",
        sa.Column("resolution_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("escrow_transactions", "resolution_reason")
    op.drop_column("escrow_transactions", "resolved_by")
