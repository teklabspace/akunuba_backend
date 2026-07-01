"""Add sequential human-readable ticket_number to support_tickets

Adds support_tickets.ticket_number backed by a Postgres sequence so every
ticket gets a short, monotonic, collision-free number (shown as "TCK-1042").
Existing rows are backfilled in created_at order; the sequence is advanced past
the max so new inserts continue cleanly.

Revision ID: 022_ticket_number
Revises: 021_advisor_clients_and_reject
Create Date: 2026-07-01

"""
from alembic import op
import sqlalchemy as sa


revision = "022_ticket_number"
down_revision = "021_advisor_clients_and_reject"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS support_ticket_number_seq")
    op.add_column(
        "support_tickets",
        sa.Column("ticket_number", sa.Integer(), nullable=True),
    )

    # Backfill existing tickets in creation order (stable tiebreak on id).
    op.execute(
        """
        WITH ordered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS rn
            FROM support_tickets
        )
        UPDATE support_tickets t
        SET ticket_number = o.rn
        FROM ordered o
        WHERE t.id = o.id
        """
    )

    # Advance the sequence past the highest backfilled value so new inserts
    # never collide with an existing number.
    op.execute(
        "SELECT setval('support_ticket_number_seq', "
        "COALESCE((SELECT MAX(ticket_number) FROM support_tickets), 0) + 1, false)"
    )

    # New rows draw their number from the sequence automatically.
    op.execute(
        "ALTER TABLE support_tickets "
        "ALTER COLUMN ticket_number SET DEFAULT nextval('support_ticket_number_seq')"
    )
    op.alter_column("support_tickets", "ticket_number", nullable=False)
    op.create_unique_constraint(
        "uq_support_tickets_ticket_number", "support_tickets", ["ticket_number"]
    )
    op.create_index(
        "ix_support_tickets_ticket_number", "support_tickets", ["ticket_number"]
    )
    # Tie the sequence's lifecycle to the column.
    op.execute(
        "ALTER SEQUENCE support_ticket_number_seq "
        "OWNED BY support_tickets.ticket_number"
    )


def downgrade() -> None:
    op.drop_index("ix_support_tickets_ticket_number", table_name="support_tickets")
    op.drop_constraint(
        "uq_support_tickets_ticket_number", "support_tickets", type_="unique"
    )
    op.drop_column("support_tickets", "ticket_number")
    op.execute("DROP SEQUENCE IF EXISTS support_ticket_number_seq")
