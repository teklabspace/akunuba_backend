"""Trading cash balance + append-only cash ledger.

Trades wrote an Order row and moved no money anywhere; there was no cash
balance in the schema at all. accounts.cash_balance is the settled trading
cash, cash_transactions is the audit trail behind every change to it.

Revision ID: 040_trading_cash_ledger
Revises: 039_activity_log
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, UUID

revision = "040_trading_cash_ledger"
down_revision = "039_activity_log"
branch_labels = None
depends_on = None


CASH_ENTRY_TYPES = ("deposit", "withdrawal", "trade_buy", "trade_sell", "adjustment")


def upgrade() -> None:
    # Existing accounts start settled at zero rather than NULL, so the balance
    # is always summable without COALESCE at the call site.
    op.add_column(
        "accounts",
        sa.Column(
            "cash_balance",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="0.00",
        ),
    )

    # Create the type once, explicitly; create_type=False stops create_table
    # from emitting a second CREATE TYPE for the same name.
    ENUM(*CASH_ENTRY_TYPES, name="cashentrytype").create(op.get_bind(), checkfirst=True)
    entry_type = ENUM(*CASH_ENTRY_TYPES, name="cashentrytype", create_type=False)

    op.create_table(
        "cash_transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("entry_type", entry_type, nullable=False),
        # Signed: negative debits, positive credits. Balance = running sum.
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(20, 2), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column(
            "linked_account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("linked_accounts.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cash_transactions_account_id", "cash_transactions", ["account_id"])
    op.create_index("ix_cash_transactions_created_at", "cash_transactions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_cash_transactions_created_at", table_name="cash_transactions")
    op.drop_index("ix_cash_transactions_account_id", table_name="cash_transactions")
    op.drop_table("cash_transactions")
    ENUM(name="cashentrytype").drop(op.get_bind(), checkfirst=True)
    op.drop_column("accounts", "cash_balance")
