"""Backfill estimated_value for never-valued assets.

QA 2026-07-18: assets created with no monetary value stored estimated_value
NULL alongside current_value 0.00, making "has this asset been valued?"
checks ambiguous. The create endpoint now writes 0.00 to both columns
(resolve_initial_values in app/api/v1/assets.py); this migration aligns the
rows created before the fix.

Only rows matching the exact no-value signature (current 0 + estimated NULL)
are touched — an asset with a real current_value keeps its NULL estimate,
since estimated_value is the AI-appraisal slot.
"""
from alembic import op

revision = "030_backfill_no_value_est"
down_revision = "029_user_avatar_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE assets
        SET estimated_value = 0.00
        WHERE estimated_value IS NULL
          AND current_value = 0.00
        """
    )


def downgrade() -> None:
    # Irreversible in principle (pre-fix rows are indistinguishable from
    # post-fix ones), and reverting to the ambiguous NULL/0 mix is never
    # desirable. Intentionally a no-op.
    pass
