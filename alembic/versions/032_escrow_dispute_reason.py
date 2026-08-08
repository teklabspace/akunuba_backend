"""Store the dispute reason on the escrow itself.

POST /marketplace/escrow/{id}/dispute accepted a reason but only forwarded it
into the admin notification text — nothing persisted it, so the admin dispute
views had no reason to show. escrow_transactions.dispute_reason now holds the
text the buyer/seller typed when raising the dispute (NULL = never disputed).
"""
from alembic import op
import sqlalchemy as sa

revision = "032_escrow_dispute_reason"
down_revision = "031_manual_kyc_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "escrow_transactions",
        sa.Column("dispute_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("escrow_transactions", "dispute_reason")
