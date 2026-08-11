"""Investment strategies table (strategies list/detail backend — QA finding B2).

Revision ID: 036_investment_strategies
Revises: 035_investment_goals
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "036_investment_strategies"
down_revision = "035_investment_goals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investment_strategies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("cloned_from", UUID(as_uuid=True), sa.ForeignKey("investment_strategies.id"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("full_description", sa.Text(), nullable=True),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("chart_type", sa.String(50), nullable=True),
        sa.Column("parameters", JSONB(), nullable=True),
        sa.Column("is_open_source", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("comment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("boost_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_investment_strategies_account_id", "investment_strategies", ["account_id"])


def downgrade() -> None:
    op.drop_table("investment_strategies")
