"""Escrow seller-payout bookkeeping: payout_status + destination last4.

Release now pays the seller amount − commission to their Plaid-linked bank
(recorded as pending until the Connect/ACH rail lands); blocked_no_bank marks
sellers who must link a bank account first. See app/services/escrow_payout.py.

Revision ID: 033_escrow_payout_fields
Revises: 032_escrow_dispute_reason
"""
import sqlalchemy as sa
from alembic import op

revision = "033_escrow_payout_fields"
down_revision = "032_escrow_dispute_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "escrow_transactions",
        sa.Column("payout_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "escrow_transactions",
        sa.Column("payout_destination_last4", sa.String(length=4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("escrow_transactions", "payout_destination_last4")
    op.drop_column("escrow_transactions", "payout_status")
