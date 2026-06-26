"""Add human-readable asset_code (AK-01, AK-02, ...) with a global sequence

Revision ID: 017_add_asset_code
Revises: 016_appraisal_comments_documents
Create Date: 2026-06-26

"""
from alembic import op
import sqlalchemy as sa


revision = "017_add_asset_code"
down_revision = "016_appraisal_comments_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the column (nullable for the backfill step).
    op.add_column("assets", sa.Column("asset_code", sa.String(length=20), nullable=True))

    # 2. Global sequence that drives every new code.
    op.execute("CREATE SEQUENCE IF NOT EXISTS asset_code_seq START WITH 1")

    # 3. Backfill existing rows in creation order: AK-01, AK-02, ...
    #    Two-digit zero padding, widening naturally past 99 (AK-100).
    op.execute(
        """
        WITH ordered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS rn
            FROM assets
        )
        UPDATE assets a
        SET asset_code = 'AK-' || LPAD(o.rn::text, 2, '0')
        FROM ordered o
        WHERE a.id = o.id
        """
    )

    # 4. Advance the sequence past the highest backfilled number so new
    #    assets continue the global run without colliding.
    op.execute("SELECT setval('asset_code_seq', GREATEST((SELECT COUNT(*) FROM assets), 1))")

    # 5. Enforce global uniqueness.
    op.create_unique_constraint("uq_assets_asset_code", "assets", ["asset_code"])
    op.create_index("ix_assets_asset_code", "assets", ["asset_code"])


def downgrade() -> None:
    op.drop_index("ix_assets_asset_code", table_name="assets")
    op.drop_constraint("uq_assets_asset_code", "assets", type_="unique")
    op.drop_column("assets", "asset_code")
    op.execute("DROP SEQUENCE IF EXISTS asset_code_seq")
