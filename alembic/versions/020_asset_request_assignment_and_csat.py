"""Add advisor assignment to asset requests and CSAT rating to support tickets.

- asset_appraisals.assigned_to, asset_sale_requests.assigned_to: the advisor/admin
  handling the request (admin support dashboard).
- support_tickets.satisfaction_rating (1-5) + satisfaction_comment: CSAT captured
  from the requester after resolution; powers the dashboard satisfaction_rate.

Revision ID: 020_asset_request_assignment_and_csat
Revises: 019_add_subscription_plan_fields
Create Date: 2026-06-30

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '020_asset_req_assign_csat'
down_revision = '019_add_subscription_plan_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'asset_appraisals',
        sa.Column('assigned_to', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
    )
    op.add_column(
        'asset_sale_requests',
        sa.Column('assigned_to', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
    )
    op.add_column('support_tickets', sa.Column('satisfaction_rating', sa.Integer(), nullable=True))
    op.add_column('support_tickets', sa.Column('satisfaction_comment', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('support_tickets', 'satisfaction_comment')
    op.drop_column('support_tickets', 'satisfaction_rating')
    op.drop_column('asset_sale_requests', 'assigned_to')
    op.drop_column('asset_appraisals', 'assigned_to')
