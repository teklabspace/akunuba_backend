"""Add referrals and referral_rewards tables

Revision ID: 013_add_referral_tables
Revises: 012_add_user_preferences_and_2fa
Create Date: 2026-05-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "013_add_referral_tables"
down_revision = "012_add_user_preferences_and_2fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    referral_status = postgresql.ENUM(
        "pending",
        "completed",
        "cancelled",
        name="referralstatus",
        create_type=True,
    )
    referral_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "referrals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "referrer_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "referred_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=True,
        ),
        sa.Column("referral_code", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("referred_email", sa.String(255), nullable=True),
        sa.Column(
            "status",
            referral_status,
            nullable=False,
            server_default=sa.text("'pending'::referralstatus"),
        ),
        sa.Column(
            "reward_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "reward_currency",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column(
            "reward_paid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("reward_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "referral_rewards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "referral_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("referrals.id"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column("reward_type", sa.String(50), nullable=False),
        sa.Column(
            "paid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.execute("ALTER TABLE referrals ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE referral_rewards ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    op.drop_table("referral_rewards")
    op.drop_table("referrals")
    referral_status = postgresql.ENUM(name="referralstatus")
    referral_status.drop(op.get_bind(), checkfirst=True)
