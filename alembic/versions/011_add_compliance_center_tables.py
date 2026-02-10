"""Add Compliance Center tables

Revision ID: 011_add_compliance_center_tables
Revises: 010_add_entity_tables
Create Date: 2024-12-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '011_add_compliance_center_tables'
down_revision = '010_add_entity_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create TaskStatus enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'taskstatus') THEN
                CREATE TYPE taskstatus AS ENUM ('pending', 'overdue', 'not_started', 'completed');
            END IF;
        END $$;
    """)
    
    # Create TaskPriority enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'taskpriority') THEN
                CREATE TYPE taskpriority AS ENUM ('high', 'medium', 'low');
            END IF;
        END $$;
    """)
    
    # Create AuditType enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'audittype') THEN
                CREATE TYPE audittype AS ENUM ('internal', 'external', 'regulatory');
            END IF;
        END $$;
    """)
    
    # Create AuditStatus enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'auditstatus') THEN
                CREATE TYPE auditstatus AS ENUM ('pending', 'in_progress', 'completed', 'overdue');
            END IF;
        END $$;
    """)
    
    # Create AlertSeverity enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'alertseverity') THEN
                CREATE TYPE alertseverity AS ENUM ('critical', 'high', 'medium', 'low');
            END IF;
        END $$;
    """)
    
    # Create AlertStatus enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'alertstatus') THEN
                CREATE TYPE alertstatus AS ENUM ('open', 'acknowledged', 'resolved', 'closed');
            END IF;
        END $$;
    """)
    
    # Create ReportStatus enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'reportstatus') THEN
                CREATE TYPE reportstatus AS ENUM ('generating', 'completed', 'failed');
            END IF;
        END $$;
    """)
    
    # Create ReportFormat enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'reportformat') THEN
                CREATE TYPE reportformat AS ENUM ('pdf', 'excel', 'csv');
            END IF;
        END $$;
    """)
    
    # Create PolicyStatus enum (if not exists)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'policystatus') THEN
                CREATE TYPE policystatus AS ENUM ('active', 'draft', 'archived');
            END IF;
        END $$;
    """)
    
    # Create compliance_tasks table
    op.create_table(
        'compliance_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=True),
        sa.Column('task_name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('assignee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'overdue', 'not_started', 'completed', name='taskstatus', create_type=False), nullable=False, server_default='not_started'),
        sa.Column('priority', postgresql.ENUM('high', 'medium', 'low', name='taskpriority', create_type=False), nullable=False, server_default='medium'),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('completion_notes', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
    )
    
    # Create compliance_task_documents table
    op.create_table(
        'compliance_task_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('compliance_tasks.id'), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    
    # Create compliance_task_comments table
    op.create_table(
        'compliance_task_comments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('compliance_tasks.id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    
    # Create compliance_task_history table
    op.create_table(
        'compliance_task_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('compliance_tasks.id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    
    # Create compliance_audits table
    op.create_table(
        'compliance_audits',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=True),
        sa.Column('audit_name', sa.String(255), nullable=False),
        sa.Column('audit_type', postgresql.ENUM('internal', 'external', 'regulatory', name='audittype', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'in_progress', 'completed', 'overdue', name='auditstatus', create_type=False), nullable=False, server_default='pending'),
        sa.Column('scheduled_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('auditor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('scope', postgresql.JSONB, nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('findings', postgresql.JSONB, nullable=True),
        sa.Column('recommendations', postgresql.JSONB, nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
    )
    
    # Create compliance_alerts table
    op.create_table(
        'compliance_alerts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=True),
        sa.Column('alert_type', sa.String(100), nullable=False),
        sa.Column('severity', postgresql.ENUM('critical', 'high', 'medium', 'low', name='alertseverity', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('open', 'acknowledged', 'resolved', 'closed', name='alertstatus', create_type=False), nullable=False, server_default='open'),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('resolved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
    )
    
    # Create compliance_scores table
    op.create_table(
        'compliance_scores',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=True),
        sa.Column('score', sa.Numeric(5, 2), nullable=False),
        sa.Column('change', sa.Numeric(5, 2), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    
    # Create compliance_metrics table
    op.create_table(
        'compliance_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=True),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('score', sa.Numeric(5, 2), nullable=False),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('issues_count', sa.Integer(), server_default='0'),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
    )
    
    # Create compliance_reports table
    op.create_table(
        'compliance_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=True),
        sa.Column('report_type', sa.String(50), nullable=False),
        sa.Column('status', postgresql.ENUM('generating', 'completed', 'failed', name='reportstatus', create_type=False), nullable=False, server_default='generating'),
        sa.Column('date_from', sa.Date(), nullable=False),
        sa.Column('date_to', sa.Date(), nullable=False),
        sa.Column('format', postgresql.ENUM('pdf', 'excel', 'csv', name='reportformat', create_type=False), nullable=False),
        sa.Column('include_sections', postgresql.JSONB, nullable=True),
        sa.Column('file_path', sa.String(500), nullable=True),
        sa.Column('download_url', sa.String(500), nullable=True),
        sa.Column('supabase_storage_path', sa.String(500), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('estimated_completion', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
    )
    
    # Create compliance_policies table
    op.create_table(
        'compliance_policies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=True),
        sa.Column('policy_name', sa.String(255), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('status', postgresql.ENUM('active', 'draft', 'archived', name='policystatus', create_type=False), nullable=False, server_default='draft'),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('last_reviewed', sa.Date(), nullable=True),
        sa.Column('next_review', sa.Date(), nullable=True),
        sa.Column('document_url', sa.String(500), nullable=True),
        sa.Column('document_path', sa.String(500), nullable=True),
        sa.Column('supabase_storage_path', sa.String(500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
    )
    
    # Enable RLS on all tables
    op.execute("ALTER TABLE compliance_tasks ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE compliance_task_documents ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE compliance_task_comments ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE compliance_task_history ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE compliance_audits ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE compliance_alerts ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE compliance_scores ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE compliance_metrics ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE compliance_reports ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE compliance_policies ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    # Drop tables
    op.drop_table('compliance_policies')
    op.drop_table('compliance_reports')
    op.drop_table('compliance_metrics')
    op.drop_table('compliance_scores')
    op.drop_table('compliance_alerts')
    op.drop_table('compliance_audits')
    op.drop_table('compliance_task_history')
    op.drop_table('compliance_task_comments')
    op.drop_table('compliance_task_documents')
    op.drop_table('compliance_tasks')
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS policystatus;")
    op.execute("DROP TYPE IF EXISTS reportformat;")
    op.execute("DROP TYPE IF EXISTS reportstatus;")
    op.execute("DROP TYPE IF EXISTS alertstatus;")
    op.execute("DROP TYPE IF EXISTS alertseverity;")
    op.execute("DROP TYPE IF EXISTS auditstatus;")
    op.execute("DROP TYPE IF EXISTS audittype;")
    op.execute("DROP TYPE IF EXISTS taskpriority;")
    op.execute("DROP TYPE IF EXISTS taskstatus;")
