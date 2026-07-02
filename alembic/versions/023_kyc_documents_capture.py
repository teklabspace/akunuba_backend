"""Capture Persona KYC docs/images + extracted fields/checks for admin review

Adds:
- kyc_verifications: extracted_fields (JSONB), checks (JSONB), capture_status
  (enum), capture_error, captured_at, reviewed_by, reviewed_at.
- kyc_documents: one row per stored file (ID front/back, selfie), pointing at a
  private Supabase bucket path.

Revision ID: 023_kyc_documents_capture
Revises: 022_ticket_number
Create Date: 2026-07-01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "023_kyc_documents_capture"
down_revision = "022_ticket_number"
branch_labels = None
depends_on = None


CAPTURE_ENUM = sa.Enum(
    "NOT_CAPTURED", "PENDING", "CAPTURED", "FAILED",
    name="kyccapturestatus",
)


def upgrade() -> None:
    CAPTURE_ENUM.create(op.get_bind(), checkfirst=True)

    op.add_column("kyc_verifications", sa.Column("extracted_fields", JSONB(), nullable=True))
    op.add_column("kyc_verifications", sa.Column("checks", JSONB(), nullable=True))
    op.add_column(
        "kyc_verifications",
        sa.Column("capture_status", CAPTURE_ENUM, nullable=False, server_default="NOT_CAPTURED"),
    )
    op.add_column("kyc_verifications", sa.Column("capture_error", sa.Text(), nullable=True))
    op.add_column("kyc_verifications", sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "kyc_verifications",
        sa.Column("reviewed_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column("kyc_verifications", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "kyc_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "kyc_id", UUID(as_uuid=True),
            sa.ForeignKey("kyc_verifications.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("persona_inquiry_id", sa.String(255), nullable=True),
        sa.Column("document_type", sa.String(64), nullable=False),
        sa.Column("bucket", sa.String(128), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("persona_source_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_kyc_documents_kyc_id", "kyc_documents", ["kyc_id"])
    op.create_index("ix_kyc_documents_account_id", "kyc_documents", ["account_id"])
    op.create_index("ix_kyc_documents_persona_inquiry_id", "kyc_documents", ["persona_inquiry_id"])


def downgrade() -> None:
    op.drop_table("kyc_documents")
    op.drop_column("kyc_verifications", "reviewed_at")
    op.drop_column("kyc_verifications", "reviewed_by")
    op.drop_column("kyc_verifications", "captured_at")
    op.drop_column("kyc_verifications", "capture_error")
    op.drop_column("kyc_verifications", "capture_status")
    op.drop_column("kyc_verifications", "checks")
    op.drop_column("kyc_verifications", "extracted_fields")
    CAPTURE_ENUM.drop(op.get_bind(), checkfirst=True)
