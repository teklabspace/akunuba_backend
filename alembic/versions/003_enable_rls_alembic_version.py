"""Enable RLS on alembic_version table

Revision ID: 003_enable_rls_alembic
Revises: 002_enable_rls
Create Date: 2024-12-14

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '003_enable_rls_alembic'
down_revision = '002_enable_rls'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable RLS on alembic_version table
    op.execute('ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    # Disable RLS on alembic_version table
    op.execute('ALTER TABLE alembic_version DISABLE ROW LEVEL SECURITY;')

