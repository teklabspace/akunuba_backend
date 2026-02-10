"""Add watchlist_items table

Revision ID: 008_add_watchlist_table
Revises: 007_make_asset_id_nullable
Create Date: 2024-01-20

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '008_add_watchlist_table'
down_revision = '007_make_asset_id_nullable'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create watchlist_items table
    op.create_table(
        'watchlist_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('marketplace_listings.id'), nullable=False),
        
        # Denormalized fields for performance
        sa.Column('listing_title', sa.String(255), nullable=False),
        sa.Column('listing_category', sa.String(100)),
        sa.Column('asking_price', sa.Numeric(20, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD', nullable=False),
        sa.Column('listing_status', postgresql.ENUM('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'ACTIVE', 'SOLD', 'CANCELLED', name='listingstatus', create_type=False), nullable=False),
        sa.Column('asset_type', sa.String(50)),
        sa.Column('thumbnail_url', sa.String(500)),
        sa.Column('price_at_added', sa.Numeric(20, 2), nullable=False),
        
        # User-specific fields
        sa.Column('notes', sa.Text()),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Create indexes for performance
    op.create_index('ix_watchlist_items_account_id', 'watchlist_items', ['account_id'])
    op.create_index('ix_watchlist_items_listing_id', 'watchlist_items', ['listing_id'])
    op.create_index('ix_watchlist_items_account_listing', 'watchlist_items', ['account_id', 'listing_id'], unique=True)


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_watchlist_items_account_listing', table_name='watchlist_items')
    op.drop_index('ix_watchlist_items_listing_id', table_name='watchlist_items')
    op.drop_index('ix_watchlist_items_account_id', table_name='watchlist_items')
    
    # Drop table
    op.drop_table('watchlist_items')
