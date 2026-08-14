"""Platform activity / audit log.

Revision ID: 039_activity_log
Revises: 038_asset_delegation
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "039_activity_log"
down_revision = "038_asset_delegation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("subject_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=True),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_activity_log_actor_id", "activity_log", ["actor_id"])
    op.create_index("ix_activity_log_subject_user_id", "activity_log", ["subject_user_id"])
    op.create_index("ix_activity_log_created_at", "activity_log", ["created_at"])


def downgrade() -> None:
    op.drop_table("activity_log")
