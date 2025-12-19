"""Add missing columns to kyb_verifications table

Revision ID: 004_add_kyb_columns
Revises: 003_enable_rls_alembic_version
Create Date: 2024-12-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_add_kyb_columns'
down_revision = '003_enable_rls_alembic_version'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add missing columns to kyb_verifications table
    op.add_column('kyb_verifications', 
        sa.Column('ownership_structure', postgresql.JSONB, nullable=True)
    )
    op.add_column('kyb_verifications', 
        sa.Column('beneficial_owners', postgresql.JSONB, nullable=True)
    )


def downgrade() -> None:
    # Remove columns
    op.drop_column('kyb_verifications', 'beneficial_owners')
    op.drop_column('kyb_verifications', 'ownership_structure')

