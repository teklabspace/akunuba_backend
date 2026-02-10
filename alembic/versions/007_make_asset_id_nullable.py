"""Make asset_id nullable in photos and documents

Revision ID: 007_make_asset_id_nullable
Revises: 006_enable_rls_asset_tables
Create Date: 2024-01-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007_make_asset_id_nullable'
down_revision = '006_enable_rls_asset_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make asset_id nullable in asset_photos table
    # Using postgresql.UUID for UUID columns
    from sqlalchemy.dialects import postgresql
    op.alter_column('asset_photos', 'asset_id',
                    existing_type=postgresql.UUID(as_uuid=True),
                    nullable=True,
                    existing_nullable=False)
    
    # Make asset_id nullable in asset_documents table
    op.alter_column('asset_documents', 'asset_id',
                    existing_type=postgresql.UUID(as_uuid=True),
                    nullable=True,
                    existing_nullable=False)


def downgrade() -> None:
    # Note: This might fail if there are NULL values
    # Set any NULL asset_ids before making it non-nullable
    from sqlalchemy.dialects import postgresql
    
    # Make asset_id non-nullable in asset_documents table
    op.alter_column('asset_documents', 'asset_id',
                    existing_type=postgresql.UUID(as_uuid=True),
                    nullable=False,
                    existing_nullable=True)
    
    # Make asset_id non-nullable in asset_photos table
    op.alter_column('asset_photos', 'asset_id',
                    existing_type=postgresql.UUID(as_uuid=True),
                    nullable=False,
                    existing_nullable=True)
