"""Add explicit subscription tier/cycle fields, cancel_at_period_end, and clean
up subscriptions held by admin/advisor accounts.

Background:
  The ``subscriptions.plan`` enum only has {FREE, MONTHLY, ANNUAL}. Purchases map
  the product tier into it (starter->FREE, pro->MONTHLY, premium->ANNUAL), so a
  $49 Starter plan is physically stored as "free" and the admin dashboard showed
  "Free" for a paid plan. Billing cycle was never stored — it was guessed from the
  period length. This migration stores both explicitly and backfills existing rows.

  It also cancels any subscription sitting on an admin/advisor account: those roles
  must not hold a plan (only investors subscribe).

Revision ID: 019_add_subscription_plan_fields
Revises: 018_notifications_user_scope
Create Date: 2026-06-30

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '019_add_subscription_plan_fields'
down_revision = '018_notifications_user_scope'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) New columns (nullable / defaulted so the add is non-blocking).
    op.add_column('subscriptions', sa.Column('plan_tier', sa.String(20), nullable=True))
    op.add_column('subscriptions', sa.Column('billing_cycle', sa.String(20), nullable=True))
    op.add_column(
        'subscriptions',
        sa.Column('cancel_at_period_end', sa.Boolean(), server_default='false', nullable=False),
    )

    # 2) Backfill plan_tier from the legacy enum (the mapping used at write time).
    #    Enum labels are stored as the uppercase member NAMES.
    op.execute("UPDATE subscriptions SET plan_tier = 'starter' WHERE plan = 'FREE'")
    op.execute("UPDATE subscriptions SET plan_tier = 'pro'     WHERE plan = 'MONTHLY'")
    op.execute("UPDATE subscriptions SET plan_tier = 'premium' WHERE plan = 'ANNUAL'")

    # 3) Backfill billing_cycle. Prefer the amount (exact annual prices), then fall
    #    back to the period length (> ~60 days => annual), else monthly.
    op.execute(
        """
        UPDATE subscriptions
        SET billing_cycle = CASE
            WHEN amount IN (470, 2870, 8630) THEN 'annual'
            WHEN current_period_start IS NOT NULL
                 AND current_period_end IS NOT NULL
                 AND (current_period_end - current_period_start) > interval '60 days'
                THEN 'annual'
            ELSE 'monthly'
        END
        """
    )

    # 4) Cancel & strip any subscription on an admin/advisor account. Those roles
    #    must never hold a plan. Role enum labels are the uppercase member names.
    op.execute(
        """
        UPDATE subscriptions
        SET status = 'CANCELLED',
            cancel_at_period_end = false,
            cancelled_at = COALESCE(cancelled_at, now())
        WHERE status <> 'CANCELLED'
          AND account_id IN (
            SELECT a.id FROM accounts a
            JOIN users u ON u.id = a.user_id
            WHERE u.role IN ('ADMIN', 'ADVISOR')
          )
        """
    )


def downgrade() -> None:
    op.drop_column('subscriptions', 'cancel_at_period_end')
    op.drop_column('subscriptions', 'billing_cycle')
    op.drop_column('subscriptions', 'plan_tier')
