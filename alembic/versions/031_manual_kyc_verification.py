"""Manual KYC verification fallback link.

When Persona verification fails, an admin can email the user a tokenized
manual-verification link; the user submits a selfie + ID document directly to
us (stored as KYCDocument rows in the private bucket). These columns hold the
link token lifecycle on kyc_verifications:

  - manual_token: the link credential (unique; NULL = no active link)
  - manual_token_expires_at: 7-day expiry
  - manual_submitted_at: when the user completed the manual submission
"""
from alembic import op
import sqlalchemy as sa

revision = "031_manual_kyc_verification"
down_revision = "030_backfill_no_value_est"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kyc_verifications", sa.Column("manual_token", sa.String(255), nullable=True))
    op.add_column("kyc_verifications", sa.Column("manual_token_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("kyc_verifications", sa.Column("manual_submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_kyc_verifications_manual_token",
        "kyc_verifications",
        ["manual_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_kyc_verifications_manual_token", table_name="kyc_verifications")
    op.drop_column("kyc_verifications", "manual_submitted_at")
    op.drop_column("kyc_verifications", "manual_token_expires_at")
    op.drop_column("kyc_verifications", "manual_token")
