"""Transfers table — persists cash-flow transfers (QA finding B4, was a stub).

Revision ID: 037_transfers
Revises: 036_investment_strategies
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "037_transfers"
down_revision = "036_investment_strategies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transfers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("transfer_type", sa.String(20), nullable=False),
        sa.Column("from_linked_account_id", UUID(as_uuid=True), sa.ForeignKey("linked_accounts.id"), nullable=True),
        sa.Column("to_linked_account_id", UUID(as_uuid=True), sa.ForeignKey("linked_accounts.id"), nullable=True),
        sa.Column("wallet_address", sa.String(255), nullable=True),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("transfer_date", sa.Date(), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False, server_default="one-time"),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("confirmation_number", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_transfers_account_id", "transfers", ["account_id"])


def downgrade() -> None:
    op.drop_table("transfers")
