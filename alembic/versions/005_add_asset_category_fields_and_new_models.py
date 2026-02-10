"""Add asset category fields and new models

Revision ID: 005_add_asset_category_fields
Revises: 004_add_kyb_columns
Create Date: 2024-12-19 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005_add_asset_category_fields'
down_revision = '004_add_kyb_columns'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create new enum types
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE assetstatus AS ENUM ('active', 'pending', 'sold', 'inactive');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE ownershiptype AS ENUM ('Sole', 'Joint', 'Trust', 'Corporate');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE condition AS ENUM ('Excellent', 'Very Good', 'Good', 'Fair', 'Poor');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE valuationtype AS ENUM ('manual', 'appraisal');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE categorygroup AS ENUM ('Assets', 'Portfolio', 'Liabilities', 'Shadow Wealth', 'Philanthropy', 'Lifestyle', 'Governance');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE appraisaltype AS ENUM ('Concierge', 'API', 'Standard', 'Comprehensive', 'Expedited', 'Insurance');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE appraisalstatus AS ENUM ('pending', 'in_progress', 'completed', 'cancelled');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE salerequeststatus AS ENUM ('pending', 'reviewed', 'approved', 'rejected', 'completed');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE transferstatus AS ENUM ('pending', 'completed', 'cancelled');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE transfertype AS ENUM ('gift', 'sale', 'inheritance');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE reporttype AS ENUM ('summary', 'detailed', 'tax', 'insurance');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create asset_categories table
    # Use existing enum type if it exists
    op.execute("""
        CREATE TABLE IF NOT EXISTS asset_categories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) NOT NULL UNIQUE,
            category_group categorygroup NOT NULL,
            description TEXT,
            icon_file VARCHAR(255),
            form_fields JSONB,
            card_fields JSONB,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )
    """)
    
    # Add new columns to assets table
    op.add_column('assets', sa.Column('category_id', postgresql.UUID(as_uuid=True), nullable=True))
    # Use existing enum type
    op.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS category_group categorygroup")
    op.add_column('assets', sa.Column('location', sa.String(255), nullable=True))
    op.add_column('assets', sa.Column('estimated_value', sa.Numeric(20, 2), nullable=True))
    op.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS status assetstatus NOT NULL DEFAULT 'active'")
    op.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS condition condition")
    op.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS ownership_type ownershiptype")
    op.add_column('assets', sa.Column('acquisition_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('assets', sa.Column('purchase_price', sa.Numeric(20, 2), nullable=True))
    op.add_column('assets', sa.Column('last_appraisal_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('assets', sa.Column('specifications', postgresql.JSONB, nullable=True))
    op.execute("ALTER TABLE assets ADD COLUMN IF NOT EXISTS valuation_type valuationtype DEFAULT 'manual'")
    
    # Make asset_type nullable for backward compatibility
    op.alter_column('assets', 'asset_type', nullable=True)
    
    # Add foreign key for category
    op.create_foreign_key('fk_assets_category_id', 'assets', 'asset_categories', ['category_id'], ['id'])
    
    # Create asset_photos table
    op.execute("""
        CREATE TABLE IF NOT EXISTS asset_photos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            asset_id UUID NOT NULL REFERENCES assets(id),
            file_name VARCHAR(255) NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            file_size INTEGER,
            mime_type VARCHAR(100),
            url VARCHAR(500) NOT NULL,
            thumbnail_url VARCHAR(500),
            supabase_storage_path VARCHAR(500),
            is_primary BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    
    # Create asset_documents table
    op.execute("""
        CREATE TABLE IF NOT EXISTS asset_documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            asset_id UUID NOT NULL REFERENCES assets(id),
            name VARCHAR(255) NOT NULL,
            document_type VARCHAR(100),
            file_name VARCHAR(255) NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            file_size INTEGER,
            mime_type VARCHAR(100),
            url VARCHAR(500) NOT NULL,
            supabase_storage_path VARCHAR(500),
            date TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    
    # Create asset_appraisals table
    op.execute("""
        CREATE TABLE IF NOT EXISTS asset_appraisals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            asset_id UUID NOT NULL REFERENCES assets(id),
            appraisal_type appraisaltype NOT NULL,
            status appraisalstatus NOT NULL DEFAULT 'pending',
            requested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            estimated_completion_date TIMESTAMP WITH TIME ZONE,
            estimated_cost NUMERIC(10, 2),
            completed_at TIMESTAMP WITH TIME ZONE,
            report_url VARCHAR(500),
            estimated_value NUMERIC(20, 2),
            notes TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )
    """)
    
    # Create asset_sale_requests table
    op.execute("""
        CREATE TABLE IF NOT EXISTS asset_sale_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            asset_id UUID NOT NULL REFERENCES assets(id),
            target_price NUMERIC(20, 2),
            sale_note TEXT,
            preferred_sale_date TIMESTAMP WITH TIME ZONE,
            status salerequeststatus NOT NULL DEFAULT 'pending',
            requested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            reviewed_at TIMESTAMP WITH TIME ZONE,
            message TEXT,
            potential_buyers JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )
    """)
    
    # Create asset_transfers table
    op.execute("""
        CREATE TABLE IF NOT EXISTS asset_transfers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            asset_id UUID NOT NULL REFERENCES assets(id),
            new_owner_email VARCHAR(255) NOT NULL,
            transfer_type transfertype NOT NULL,
            status transferstatus NOT NULL DEFAULT 'pending',
            notes TEXT,
            initiated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            completed_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE
        )
    """)
    
    # Create asset_shares table
    op.execute("""
        CREATE TABLE IF NOT EXISTS asset_shares (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            asset_id UUID NOT NULL REFERENCES assets(id),
            share_link VARCHAR(500) NOT NULL UNIQUE,
            access_code VARCHAR(50),
            email VARCHAR(255),
            expires_at TIMESTAMP WITH TIME ZONE,
            permissions JSONB,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    
    # Create asset_reports table
    op.execute("""
        CREATE TABLE IF NOT EXISTS asset_reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            asset_id UUID NOT NULL REFERENCES assets(id),
            report_type reporttype NOT NULL,
            report_url VARCHAR(500),
            include_documents BOOLEAN DEFAULT FALSE,
            include_value_history BOOLEAN DEFAULT FALSE,
            include_appraisals BOOLEAN DEFAULT FALSE,
            generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            expires_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    
    # Fix asset_valuations table - make currency and valuation_date nullable if needed
    op.alter_column('asset_valuations', 'currency', nullable=True)
    op.alter_column('asset_valuations', 'valuation_date', nullable=True)
    op.alter_column('asset_valuations', 'valuation_method', type_=sa.String(50))


def downgrade() -> None:
    # Drop new tables
    op.drop_table('asset_reports')
    op.drop_table('asset_shares')
    op.drop_table('asset_transfers')
    op.drop_table('asset_sale_requests')
    op.drop_table('asset_appraisals')
    op.drop_table('asset_documents')
    op.drop_table('asset_photos')
    
    # Remove foreign key and columns from assets
    op.drop_constraint('fk_assets_category_id', 'assets', type_='foreignkey')
    op.drop_column('assets', 'valuation_type')
    op.drop_column('assets', 'specifications')
    op.drop_column('assets', 'last_appraisal_date')
    op.drop_column('assets', 'purchase_price')
    op.drop_column('assets', 'acquisition_date')
    op.drop_column('assets', 'ownership_type')
    op.drop_column('assets', 'condition')
    op.drop_column('assets', 'status')
    op.drop_column('assets', 'estimated_value')
    op.drop_column('assets', 'location')
    op.drop_column('assets', 'category_group')
    op.drop_column('assets', 'category_id')
    
    # Make asset_type not nullable again
    op.alter_column('assets', 'asset_type', nullable=False)
    
    # Drop asset_categories table
    op.drop_table('asset_categories')
    
    # Revert asset_valuations changes
    op.alter_column('asset_valuations', 'valuation_method', type_=sa.String(100))
    op.alter_column('asset_valuations', 'valuation_date', nullable=False)
    op.alter_column('asset_valuations', 'currency', nullable=False)
    
    # Drop enum types (be careful - only if not used elsewhere)
    op.execute('DROP TYPE IF EXISTS reporttype')
    op.execute('DROP TYPE IF EXISTS transfertype')
    op.execute('DROP TYPE IF EXISTS transferstatus')
    op.execute('DROP TYPE IF EXISTS salerequeststatus')
    op.execute('DROP TYPE IF EXISTS appraisalstatus')
    op.execute('DROP TYPE IF EXISTS appraisaltype')
    op.execute('DROP TYPE IF EXISTS categorygroup')
    op.execute('DROP TYPE IF EXISTS valuationtype')
    op.execute('DROP TYPE IF EXISTS condition')
    op.execute('DROP TYPE IF EXISTS ownershiptype')
    op.execute('DROP TYPE IF EXISTS assetstatus')
