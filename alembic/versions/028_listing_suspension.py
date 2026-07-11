"""Listing suspension during open human appraisals.

Adds the 'SUSPENDED' label to the listingstatus enum (labels are uppercase
member names, per 001) plus bookkeeping columns on marketplace_listings:

- pre_suspension_status: status held before suspension (restore target when a
  human appraisal is cancelled/fails).
- suspended_at: when the listing was pulled from the public marketplace.

Postgres cannot drop enum labels, so downgrade only removes the columns after
restoring any SUSPENDED rows to their prior status; the label remains unused.

Revision ID: 028_listing_suspension
Revises: 027_stripe_subscription_billing
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "028_listing_suspension"
down_revision = "027_stripe_subscription_billing"
branch_labels = None
depends_on = None

LISTING_STATUS = postgresql.ENUM(
    "DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "ACTIVE",
    "SUSPENDED", "SOLD", "CANCELLED",
    name="listingstatus", create_type=False,
)


def upgrade():
    # Commit the new label outside the migration transaction so the column
    # (and any later data migration) can reference it safely on all PG versions.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE listingstatus ADD VALUE IF NOT EXISTS 'SUSPENDED'")

    op.add_column(
        "marketplace_listings",
        sa.Column("pre_suspension_status", LISTING_STATUS, nullable=True),
    )
    op.add_column(
        "marketplace_listings",
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    # Put suspended listings back to their prior (or approved) state before the
    # bookkeeping needed to restore them disappears.
    op.execute(
        "UPDATE marketplace_listings "
        "SET status = COALESCE(pre_suspension_status, 'APPROVED') "
        "WHERE status = 'SUSPENDED'"
    )
    op.drop_column("marketplace_listings", "suspended_at")
    op.drop_column("marketplace_listings", "pre_suspension_status")
