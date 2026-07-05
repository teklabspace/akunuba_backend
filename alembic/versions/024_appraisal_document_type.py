"""Add document_type to appraisal_documents

Enables categorizing an appraisal document (e.g. "valuation"). A staff-set
"valuation" document is one of the two conditions that auto-publish an asset to
the marketplace (the other being a saved valuation amount).

Revision ID: 024_appraisal_doc_type
Revises: 023_kyc_documents_capture
Create Date: 2026-07-03

"""
from alembic import op
import sqlalchemy as sa


revision = "024_appraisal_doc_type"
down_revision = "023_kyc_documents_capture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "appraisal_documents",
        sa.Column("document_type", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("appraisal_documents", "document_type")
