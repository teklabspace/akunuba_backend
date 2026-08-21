"""Plaid account categorization + investment holdings + liabilities

Phase 1 treated every linked account as cash. This adds Plaid's real
type/subtype per account (so checking/savings/brokerage/401k/mortgage/credit
card/etc. are distinguished instead of collapsed into "banking"), plus
storage for investment holdings and liability detail — Plaid's Investments
and Liabilities products, requested going forward alongside the existing
Transactions/Auth (see app/integrations/plaid_client.py).

Existing linked_accounts rows predate this and were only ever cash/bank
accounts (Phase 1 scope) — backfilled to plaid_type='depository' so the new
"is this cash?" filters in portfolio/investment/accounts/reports don't drop
them from cash_available.

Revision ID: 046_plaid_categorization
Revises: 045_one_escrow_per_offer
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "046_plaid_categorization"
down_revision = "045_one_escrow_per_offer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- LinkedAccount: real Plaid identity + type/subtype ---
    op.add_column("linked_accounts", sa.Column("plaid_account_id", sa.String(255), nullable=True))
    op.add_column("linked_accounts", sa.Column("plaid_type", sa.String(50), nullable=True))
    op.add_column("linked_accounts", sa.Column("plaid_subtype", sa.String(100), nullable=True))

    # Every existing row predates categorization and was Phase 1 (cash-only) scope.
    op.execute("UPDATE linked_accounts SET plaid_type = 'depository' WHERE plaid_type IS NULL")

    # Credit/loan accounts must resolve to OTHER, not BANKING — the payout
    # eligibility filter in app/services/escrow_payout.py depends on that.
    op.execute("ALTER TYPE linkedaccounttype ADD VALUE IF NOT EXISTS 'OTHER'")

    # --- Securities (shared cache; holdings reference these) ---
    op.create_table(
        "securities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("plaid_security_id", sa.String(255), nullable=False, unique=True),
        sa.Column("ticker_symbol", sa.String(20), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("security_type", sa.String(50), nullable=True),
        sa.Column("close_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("close_price_as_of", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True, server_default="USD"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_securities_plaid_security_id", "securities", ["plaid_security_id"], unique=True)

    # --- Investment holdings (full snapshot per sync, not append-only) ---
    op.create_table(
        "investment_holdings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("linked_account_id", UUID(as_uuid=True), sa.ForeignKey("linked_accounts.id"), nullable=False),
        sa.Column("security_id", UUID(as_uuid=True), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("cost_basis", sa.Numeric(20, 2), nullable=True),
        sa.Column("institution_value", sa.Numeric(20, 2), nullable=False),
        sa.Column("institution_price", sa.Numeric(20, 4), nullable=True),
        sa.Column("institution_price_as_of", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True, server_default="USD"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("linked_account_id", "security_id", name="uq_holding_account_security"),
    )
    op.create_index("ix_investment_holdings_linked_account_id", "investment_holdings", ["linked_account_id"])

    # --- Liabilities (one row per credit/mortgage/student-loan account) ---
    op.create_table(
        "liabilities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "linked_account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("linked_accounts.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("liability_type", sa.String(20), nullable=False),
        sa.Column("last_payment_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("last_payment_date", sa.Date(), nullable=True),
        sa.Column("next_payment_due_date", sa.Date(), nullable=True),
        sa.Column("minimum_payment_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("last_statement_balance", sa.Numeric(20, 2), nullable=True),
        sa.Column("is_overdue", sa.Boolean(), nullable=True),
        sa.Column("details", JSONB, nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("liabilities")
    op.drop_index("ix_investment_holdings_linked_account_id", table_name="investment_holdings")
    op.drop_table("investment_holdings")
    op.drop_index("ix_securities_plaid_security_id", table_name="securities")
    op.drop_table("securities")
    # Postgres has no ALTER TYPE ... DROP VALUE — 'OTHER' stays defined but
    # unused after downgrade.
    op.drop_column("linked_accounts", "plaid_subtype")
    op.drop_column("linked_accounts", "plaid_type")
    op.drop_column("linked_accounts", "plaid_account_id")
