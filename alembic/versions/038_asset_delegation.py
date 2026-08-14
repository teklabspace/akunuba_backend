"""Delegated asset creation — advisor_requests + asset_delegation_grants.

Revision ID: 038_asset_delegation
Revises: 037_transfers
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "038_asset_delegation"
down_revision = "037_transfers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "advisor_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("investor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_advisor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decided_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_advisor_requests_investor_id", "advisor_requests", ["investor_id"])
    # At most one open request per investor.
    op.create_index(
        "uq_advisor_requests_one_pending",
        "advisor_requests",
        ["investor_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "asset_delegation_grants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("advisor_requests.id"), nullable=True),
        sa.Column("investor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("advisor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("asset_id", UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_delegation_grants_investor_id", "asset_delegation_grants", ["investor_id"])
    op.create_index("ix_delegation_grants_advisor_id", "asset_delegation_grants", ["advisor_id"])
    # One live grant per (investor, advisor) pair.
    op.create_index(
        "uq_delegation_grants_one_active",
        "asset_delegation_grants",
        ["investor_id", "advisor_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("asset_delegation_grants")
    op.drop_table("advisor_requests")
