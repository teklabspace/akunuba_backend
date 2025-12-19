"""Enable RLS on all tables

Revision ID: 002_enable_rls
Revises: 001_initial
Create Date: 2024-12-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002_enable_rls'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # List of all tables that need RLS enabled
    tables = [
        'users',
        'accounts',
        'joint_account_invitations',
        'kyc_verifications',
        'kyb_verifications',
        'assets',
        'asset_valuations',
        'asset_ownership',
        'portfolios',
        'orders',
        'order_history',
        'marketplace_listings',
        'offers',
        'escrow_transactions',
        'payments',
        'refunds',
        'invoices',
        'subscriptions',
        'linked_accounts',
        'transactions',
        'documents',
        'support_tickets',
        'ticket_replies',
        'notifications',
        'alembic_version',  # Alembic's version tracking table
    ]
    
    # Enable RLS on all tables
    for table in tables:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    # List of all tables that need RLS disabled
    tables = [
        'users',
        'accounts',
        'joint_account_invitations',
        'kyc_verifications',
        'kyb_verifications',
        'assets',
        'asset_valuations',
        'asset_ownership',
        'portfolios',
        'orders',
        'order_history',
        'marketplace_listings',
        'offers',
        'escrow_transactions',
        'payments',
        'refunds',
        'invoices',
        'subscriptions',
        'linked_accounts',
        'transactions',
        'documents',
        'support_tickets',
        'ticket_replies',
        'notifications',
        'alembic_version',  # Alembic's version tracking table
    ]
    
    # Disable RLS on all tables
    for table in tables:
        op.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;')

