"""Stripe subscription billing: account customer id + INCOMPLETE subscription status.

Adds accounts.stripe_customer_id and extends the subscriptionstatus enum with
INCOMPLETE, the state a subscription sits in between creation and the
invoice.payment_succeeded webhook. Access is denied while INCOMPLETE because
ACCESS_GRANTING_STATUSES (app/api/deps.py) lists only ACTIVE and PAST_DUE.

Note: SQLAlchemy's SQLEnum persists the enum NAME, so the stored label is the
uppercase 'INCOMPLETE', matching the existing ACTIVE/CANCELLED/EXPIRED/PAST_DUE.

Revision ID: 027_stripe_subscription_billing
Revises: 026_escrow_resolution_audit
"""
from alembic import op
import sqlalchemy as sa


revision = "027_stripe_subscription_billing"
down_revision = "026_escrow_resolution_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("stripe_customer_id", sa.String(255), nullable=True))
    op.create_index("ix_accounts_stripe_customer_id", "accounts", ["stripe_customer_id"])

    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on PostgreSQL
    # older than 12, and Alembic wraps migrations in one. autocommit_block() steps out.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE subscriptionstatus ADD VALUE IF NOT EXISTS 'INCOMPLETE'")


def downgrade() -> None:
    op.drop_index("ix_accounts_stripe_customer_id", table_name="accounts")
    op.drop_column("accounts", "stripe_customer_id")
    # PostgreSQL cannot DROP a value from an enum type. Any row still holding
    # INCOMPLETE would be orphaned, so the label is deliberately left in place.
