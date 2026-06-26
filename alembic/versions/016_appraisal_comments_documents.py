"""Structured appraisal comments + documents (client-visible tracking)

Revision ID: 016_appraisal_comments_documents
Revises: 015_extend_ai_appraisal
Create Date: 2026-06-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "016_appraisal_comments_documents"
down_revision = "015_extend_ai_appraisal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appraisal_comments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("appraisal_id", UUID(as_uuid=True), sa.ForeignKey("asset_appraisals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("author_role", sa.String(length=20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("comment_type", sa.String(length=20), nullable=False, server_default="message"),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_appraisal_comments_appraisal_id", "appraisal_comments", ["appraisal_id"])

    op.create_table(
        "appraisal_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("appraisal_id", UUID(as_uuid=True), sa.ForeignKey("asset_appraisals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_by_role", sa.String(length=20), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("is_client_visible", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("fulfills_comment_id", UUID(as_uuid=True), sa.ForeignKey("appraisal_comments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_appraisal_documents_appraisal_id", "appraisal_documents", ["appraisal_id"])


def downgrade() -> None:
    op.drop_index("ix_appraisal_documents_appraisal_id", table_name="appraisal_documents")
    op.drop_table("appraisal_documents")
    op.drop_index("ix_appraisal_comments_appraisal_id", table_name="appraisal_comments")
    op.drop_table("appraisal_comments")
