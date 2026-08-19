"""Backfill + default support_tickets.updated_at.

updated_at had onupdate=func.now() but no server_default, so any ticket
never edited after creation had updated_at = NULL -- visible in the admin
payload itself (TCK-0008: "updated_at": null). The frontend's "Last
updated" column was permanently empty for those rows; the API now falls
back to created_at in the response, but the column should carry a real
value too, both for existing rows and every ticket created from here on.

Revision ID: 043_ticket_updated_at_default
Revises: 042_platform_report_type
"""
import sqlalchemy as sa
from alembic import op

revision = "043_ticket_updated_at_default"
down_revision = "042_platform_report_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE support_tickets SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column(
        "support_tickets",
        "updated_at",
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.alter_column(
        "support_tickets",
        "updated_at",
        server_default=None,
    )
