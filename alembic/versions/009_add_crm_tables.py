"""Add CRM Dashboard tables (reports and document_shares)

Revision ID: 009_add_crm_tables
Revises: 008_add_watchlist_table
Create Date: 2024-12-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '009_add_crm_tables'
down_revision = '008_add_watchlist_table'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create ReportType enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE reporttype AS ENUM ('portfolio', 'performance', 'transaction', 'tax', 'custom');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create ReportStatus enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE reportstatus AS ENUM ('pending', 'generating', 'completed', 'failed');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create ReportFormat enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE reportformat AS ENUM ('pdf', 'csv', 'xlsx', 'json');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create SharePermission enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE sharepermission AS ENUM ('view', 'download', 'edit');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create reports table
    op.create_table(
        'reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('report_type', postgresql.ENUM('portfolio', 'performance', 'transaction', 'tax', 'custom', name='reporttype', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'generating', 'completed', 'failed', name='reportstatus', create_type=False), nullable=False, server_default='pending'),
        sa.Column('format', postgresql.ENUM('pdf', 'csv', 'xlsx', 'json', name='reportformat', create_type=False), nullable=False, server_default='pdf'),
        sa.Column('start_date', sa.DateTime(timezone=True)),
        sa.Column('end_date', sa.DateTime(timezone=True)),
        sa.Column('filters', postgresql.JSONB),
        sa.Column('parameters', postgresql.JSONB),
        sa.Column('file_path', sa.String(500)),
        sa.Column('file_size', sa.Integer()),
        sa.Column('file_url', sa.String(500)),
        sa.Column('supabase_storage_path', sa.String(500)),
        sa.Column('generated_at', sa.DateTime(timezone=True)),
        sa.Column('error_message', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Create document_shares table
    op.create_table(
        'document_shares',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('shared_with_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('permission', postgresql.ENUM('view', 'download', 'edit', name='sharepermission', create_type=False), nullable=False, server_default='view'),
        sa.Column('share_link', sa.String(500)),
        sa.Column('share_token', sa.String(100), unique=True),
        sa.Column('expiry_date', sa.DateTime(timezone=True)),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Create indexes
    op.create_index('ix_reports_account_id', 'reports', ['account_id'])
    op.create_index('ix_reports_status', 'reports', ['status'])
    op.create_index('ix_document_shares_document_id', 'document_shares', ['document_id'])
    op.create_index('ix_document_shares_shared_with_user_id', 'document_shares', ['shared_with_user_id'])
    op.create_index('ix_document_shares_share_token', 'document_shares', ['share_token'])
    
    # Enable RLS on new tables
    op.execute('ALTER TABLE reports ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE document_shares ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_document_shares_share_token', 'document_shares')
    op.drop_index('ix_document_shares_shared_with_user_id', 'document_shares')
    op.drop_index('ix_document_shares_document_id', 'document_shares')
    op.drop_index('ix_reports_status', 'reports')
    op.drop_index('ix_reports_account_id', 'reports')
    
    # Drop tables
    op.drop_table('document_shares')
    op.drop_table('reports')
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS sharepermission")
    op.execute("DROP TYPE IF EXISTS reportformat")
    op.execute("DROP TYPE IF EXISTS reportstatus")
    op.execute("DROP TYPE IF EXISTS reporttype")
