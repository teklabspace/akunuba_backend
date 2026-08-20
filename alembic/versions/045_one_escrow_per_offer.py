"""Enforce one escrow per offer at the database level

Defence in depth for a race found in the 2026-08-19 QA audit. `accept_offer` did a
check-then-act (read offer -> test status == PENDING -> create escrow) with no row lock, so
concurrent accepts all observed PENDING and every one proceeded. Reproduced: 5 parallel
accepts of a single 400,000 offer returned 200 five times and produced 5 escrow rows
totalling 2,000,000, each carrying its own Stripe PaymentIntent against the same buyer.

The primary fix is `SELECT ... FOR UPDATE` on the offer row in accept_offer. This unique
index is the backstop: even if a future refactor drops the lock, or two application
instances race in a way the lock does not cover, the second insert fails instead of
silently duplicating a financial record.

Duplicates are collapsed before the index is created, keeping the oldest escrow per offer.
Rows with NULL offer_id are unaffected (the index only constrains non-null offer_id).

Revision ID: 045_one_escrow_per_offer
Revises: 044_schema_drift
"""
from alembic import op
import sqlalchemy as sa

revision = "045_one_escrow_per_offer"
down_revision = "044_schema_drift"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_escrow_transactions_offer_id"


def upgrade() -> None:
    bind = op.get_bind()

    # Collapse any pre-existing duplicates, keeping the earliest escrow for each offer.
    # Only PENDING duplicates are removed: anything already funded, released, refunded or
    # disputed represents real money movement and must never be deleted by a migration.
    # If a non-PENDING duplicate exists the index creation below will fail loudly, which is
    # the correct outcome - that needs a human, not an automatic delete.
    bind.execute(sa.text("""
        DELETE FROM escrow_transactions e
        USING (
            SELECT offer_id, MIN(created_at) AS keep_created
            FROM escrow_transactions
            WHERE offer_id IS NOT NULL
            GROUP BY offer_id
            HAVING COUNT(*) > 1
        ) d
        WHERE e.offer_id = d.offer_id
          AND e.created_at > d.keep_created
          AND e.status = 'PENDING'
    """))

    op.create_index(
        INDEX_NAME,
        "escrow_transactions",
        ["offer_id"],
        unique=True,
        postgresql_where=sa.text("offer_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="escrow_transactions")
