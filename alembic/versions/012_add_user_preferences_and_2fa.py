"""Add User Preferences and 2FA

Revision ID: 012_add_user_preferences_and_2fa
Revises: 011_add_compliance_center_tables
Create Date: 2024-12-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '012_add_user_preferences_and_2fa'
down_revision = '011_add_compliance_center_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 2FA fields to users table
    op.add_column('users', sa.Column('two_factor_auth_enabled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users', sa.Column('two_factor_auth_verified', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users', sa.Column('two_factor_auth_secret', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('two_factor_auth_method', sa.String(20), nullable=True))
    op.add_column('users', sa.Column('two_factor_backup_codes', sa.String(1000), nullable=True))
    op.add_column('users', sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True))
    
    # Create user_preferences table
    op.create_table(
        'user_preferences',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), unique=True, nullable=False),
        sa.Column('email_alerts', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('push_notifications', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('weekly_reports', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('market_updates', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('profile_visible', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('show_portfolio', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
    )
    
    # Enable RLS on user_preferences table
    op.execute("ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    # Drop user_preferences table
    op.drop_table('user_preferences')
    
    # Remove 2FA fields from users table
    op.drop_column('users', 'deactivated_at')
    op.drop_column('users', 'two_factor_backup_codes')
    op.drop_column('users', 'two_factor_auth_method')
    op.drop_column('users', 'two_factor_auth_secret')
    op.drop_column('users', 'two_factor_auth_verified')
    op.drop_column('users', 'two_factor_auth_enabled')
