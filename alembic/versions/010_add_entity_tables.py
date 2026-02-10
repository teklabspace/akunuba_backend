"""Add Entity Structure tables

Revision ID: 010_add_entity_tables
Revises: 009_add_crm_tables
Create Date: 2024-12-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '010_add_entity_tables'
down_revision = '009_add_crm_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create EntityType enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE entitytype AS ENUM ('LLC', 'Corporation', 'Trust', 'Partnership', 'Foundation', 'Other');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create EntityStatus enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE entitystatus AS ENUM ('active', 'inactive', 'pending', 'suspended', 'dissolved');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create EntityRole enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE entityrole AS ENUM ('trustee', 'signatory', 'power_of_attorney', 'director', 'officer', 'member', 'manager', 'beneficiary', 'other');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create EntityDocumentType enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE entitydocumenttype AS ENUM ('articles_of_incorporation', 'trust_deed', 'operating_agreement', 'bylaws', 'certificate_of_formation', 'ein_document', 'tax_document', 'compliance_document', 'other');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create DocumentStatus enum (for entities)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE documentstatus AS ENUM ('pending', 'approved', 'rejected');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create ComplianceStatus enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE compliancestatus AS ENUM ('pending', 'verified', 'not_compliant', 'compliant');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create AuditAction enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE auditaction AS ENUM ('entity_created', 'entity_updated', 'entity_deleted', 'document_uploaded', 'document_approved', 'document_rejected', 'status_updated', 'person_added', 'person_removed', 'person_updated', 'compliance_updated', 'note_added', 'relationship_updated');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create entities table
    op.create_table(
        'entities',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('entity_type', postgresql.ENUM('LLC', 'Corporation', 'Trust', 'Partnership', 'Foundation', 'Other', name='entitytype', create_type=False), nullable=False),
        sa.Column('jurisdiction', sa.String(100)),
        sa.Column('location', sa.String(255)),
        sa.Column('registration_number', sa.String(100)),
        sa.Column('formation_date', sa.Date()),
        sa.Column('status', postgresql.ENUM('active', 'inactive', 'pending', 'suspended', 'dissolved', name='entitystatus', create_type=False), nullable=False, server_default='pending'),
        sa.Column('parent_entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=True),
        sa.Column('description', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Create entity_compliance table
    op.create_table(
        'entity_compliance',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=False, unique=True),
        sa.Column('kyc_aml_status', postgresql.ENUM('pending', 'verified', 'not_compliant', 'compliant', name='compliancestatus', create_type=False), default='pending'),
        sa.Column('registered_agent', sa.String(255)),
        sa.Column('tax_residency', sa.String(100)),
        sa.Column('fatca_crs_compliance', postgresql.ENUM('pending', 'verified', 'not_compliant', 'compliant', name='compliancestatus', create_type=False), default='pending'),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Create entity_people table
    op.create_table(
        'entity_people',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('role', postgresql.ENUM('trustee', 'signatory', 'power_of_attorney', 'director', 'officer', 'member', 'manager', 'beneficiary', 'other', name='entityrole', create_type=False), nullable=False),
        sa.Column('email', sa.String(255)),
        sa.Column('phone', sa.String(50)),
        sa.Column('notes', sa.Text()),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Create entity_documents table
    op.create_table(
        'entity_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('document_type', postgresql.ENUM('articles_of_incorporation', 'trust_deed', 'operating_agreement', 'bylaws', 'certificate_of_formation', 'ein_document', 'tax_document', 'compliance_document', 'other', name='entitydocumenttype', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'approved', 'rejected', name='documentstatus', create_type=False), nullable=False, server_default='pending'),
        sa.Column('file_path', sa.String(500)),
        sa.Column('file_url', sa.String(500)),
        sa.Column('supabase_storage_path', sa.String(500)),
        sa.Column('file_size', sa.Integer()),
        sa.Column('mime_type', sa.String(100)),
        sa.Column('uploaded_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id')),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('description', sa.Text()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    
    # Create entity_audit_trail table
    op.create_table(
        'entity_audit_trail',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entities.id'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('action', postgresql.ENUM('entity_created', 'entity_updated', 'entity_deleted', 'document_uploaded', 'document_approved', 'document_rejected', 'status_updated', 'person_added', 'person_removed', 'person_updated', 'compliance_updated', 'note_added', 'relationship_updated', name='auditaction', create_type=False), nullable=False),
        sa.Column('action_display', sa.String(255)),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('entity_documents.id'), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('status_display', sa.String(255)),
        sa.Column('notes', sa.Text()),
        sa.Column('metadata', postgresql.JSONB),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # Create indexes
    op.create_index('ix_entities_account_id', 'entities', ['account_id'])
    op.create_index('ix_entities_status', 'entities', ['status'])
    op.create_index('ix_entities_parent_entity_id', 'entities', ['parent_entity_id'])
    op.create_index('ix_entity_people_entity_id', 'entity_people', ['entity_id'])
    op.create_index('ix_entity_people_role', 'entity_people', ['role'])
    op.create_index('ix_entity_documents_entity_id', 'entity_documents', ['entity_id'])
    op.create_index('ix_entity_documents_status', 'entity_documents', ['status'])
    op.create_index('ix_entity_audit_trail_entity_id', 'entity_audit_trail', ['entity_id'])
    op.create_index('ix_entity_audit_trail_timestamp', 'entity_audit_trail', ['timestamp'])
    
    # Enable RLS on new tables
    op.execute('ALTER TABLE entities ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE entity_compliance ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE entity_people ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE entity_documents ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE entity_audit_trail ENABLE ROW LEVEL SECURITY;')


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_entity_audit_trail_timestamp', 'entity_audit_trail')
    op.drop_index('ix_entity_audit_trail_entity_id', 'entity_audit_trail')
    op.drop_index('ix_entity_documents_status', 'entity_documents')
    op.drop_index('ix_entity_documents_entity_id', 'entity_documents')
    op.drop_index('ix_entity_people_role', 'entity_people')
    op.drop_index('ix_entity_people_entity_id', 'entity_people')
    op.drop_index('ix_entities_parent_entity_id', 'entities')
    op.drop_index('ix_entities_status', 'entities')
    op.drop_index('ix_entities_account_id', 'entities')
    
    # Drop tables
    op.drop_table('entity_audit_trail')
    op.drop_table('entity_documents')
    op.drop_table('entity_people')
    op.drop_table('entity_compliance')
    op.drop_table('entities')
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS auditaction")
    op.execute("DROP TYPE IF EXISTS compliancestatus")
    op.execute("DROP TYPE IF EXISTS documentstatus")
    op.execute("DROP TYPE IF EXISTS entitydocumenttype")
    op.execute("DROP TYPE IF EXISTS entityrole")
    op.execute("DROP TYPE IF EXISTS entitystatus")
    op.execute("DROP TYPE IF EXISTS entitytype")
