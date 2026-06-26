"""Make notifications user-addressable + add APPRAISAL_MESSAGE type

Adds notifications.user_id (so staff without an account can receive
notifications), relaxes account_id to nullable, backfills user_id from the
owning account, and adds the APPRAISAL_MESSAGE enum value.

Revision ID: 018_notifications_user_scope
Revises: 017_add_asset_code
Create Date: 2026-06-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "018_notifications_user_scope"
down_revision = "017_add_asset_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New enum label is the UPPERCASE member name (SQLAlchemy stores names).
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'APPRAISAL_MESSAGE'")

    op.add_column(
        "notifications",
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.alter_column("notifications", "account_id", existing_type=UUID(as_uuid=True), nullable=True)

    # Backfill user_id from each notification's owning account.
    op.execute(
        """
        UPDATE notifications n
        SET user_id = a.user_id
        FROM accounts a
        WHERE n.account_id = a.id AND n.user_id IS NULL
        """
    )

    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_column("notifications", "user_id")
    op.alter_column("notifications", "account_id", existing_type=UUID(as_uuid=True), nullable=False)
    # Enum value removal is unsupported in PostgreSQL; APPRAISAL_MESSAGE remains.
