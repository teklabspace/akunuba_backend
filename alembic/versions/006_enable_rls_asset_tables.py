"""Enable RLS on new asset-related tables

Revision ID: 006_enable_rls_asset_tables
Revises: 005_add_asset_category_fields
Create Date: 2024-12-19 16:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '006_enable_rls_asset_tables'
down_revision = '005_add_asset_category_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # List of new asset-related tables that need RLS enabled
    asset_tables = [
        'asset_photos',
        'asset_documents',
        'asset_appraisals',
        'asset_sale_requests',
        'asset_transfers',
        'asset_shares',
        'asset_reports',
        'asset_categories',  # Also enable for asset_categories (public read-only)
    ]
    
    # Enable RLS on all asset-related tables
    for table in asset_tables:
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;')
    
    # Create RLS policies for asset_photos
    # Users can access photos for assets they own
    op.execute("""
        CREATE POLICY "Users can view asset photos for their assets"
        ON asset_photos FOR SELECT
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can insert asset photos for their assets"
        ON asset_photos FOR INSERT
        TO authenticated
        WITH CHECK (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can update asset photos for their assets"
        ON asset_photos FOR UPDATE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can delete asset photos for their assets"
        ON asset_photos FOR DELETE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    # Create RLS policies for asset_documents (same pattern)
    op.execute("""
        CREATE POLICY "Users can view asset documents for their assets"
        ON asset_documents FOR SELECT
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can insert asset documents for their assets"
        ON asset_documents FOR INSERT
        TO authenticated
        WITH CHECK (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can update asset documents for their assets"
        ON asset_documents FOR UPDATE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can delete asset documents for their assets"
        ON asset_documents FOR DELETE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    # Create RLS policies for asset_appraisals
    op.execute("""
        CREATE POLICY "Users can view asset appraisals for their assets"
        ON asset_appraisals FOR SELECT
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can insert asset appraisals for their assets"
        ON asset_appraisals FOR INSERT
        TO authenticated
        WITH CHECK (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can update asset appraisals for their assets"
        ON asset_appraisals FOR UPDATE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can delete asset appraisals for their assets"
        ON asset_appraisals FOR DELETE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    # Create RLS policies for asset_sale_requests
    op.execute("""
        CREATE POLICY "Users can view asset sale requests for their assets"
        ON asset_sale_requests FOR SELECT
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can insert asset sale requests for their assets"
        ON asset_sale_requests FOR INSERT
        TO authenticated
        WITH CHECK (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can update asset sale requests for their assets"
        ON asset_sale_requests FOR UPDATE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can delete asset sale requests for their assets"
        ON asset_sale_requests FOR DELETE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    # Create RLS policies for asset_transfers
    op.execute("""
        CREATE POLICY "Users can view asset transfers for their assets"
        ON asset_transfers FOR SELECT
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can insert asset transfers for their assets"
        ON asset_transfers FOR INSERT
        TO authenticated
        WITH CHECK (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can update asset transfers for their assets"
        ON asset_transfers FOR UPDATE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can delete asset transfers for their assets"
        ON asset_transfers FOR DELETE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    # Create RLS policies for asset_shares
    op.execute("""
        CREATE POLICY "Users can view asset shares for their assets"
        ON asset_shares FOR SELECT
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can insert asset shares for their assets"
        ON asset_shares FOR INSERT
        TO authenticated
        WITH CHECK (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can update asset shares for their assets"
        ON asset_shares FOR UPDATE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can delete asset shares for their assets"
        ON asset_shares FOR DELETE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    # Create RLS policies for asset_reports
    op.execute("""
        CREATE POLICY "Users can view asset reports for their assets"
        ON asset_reports FOR SELECT
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can insert asset reports for their assets"
        ON asset_reports FOR INSERT
        TO authenticated
        WITH CHECK (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can update asset reports for their assets"
        ON asset_reports FOR UPDATE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    op.execute("""
        CREATE POLICY "Users can delete asset reports for their assets"
        ON asset_reports FOR DELETE
        TO authenticated
        USING (
            asset_id IN (
                SELECT id FROM assets 
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE user_id = auth.uid()
                )
            )
        );
    """)
    
    # Create RLS policy for asset_categories (public read-only)
    # Categories should be readable by all authenticated users, but only admins can modify
    op.execute("""
        CREATE POLICY "Authenticated users can view asset categories"
        ON asset_categories FOR SELECT
        TO authenticated
        USING (true);
    """)
    
    # Note: Only service role (backend) can insert/update/delete categories
    # No policy needed for modification as service role bypasses RLS


def downgrade() -> None:
    # Drop all policies first (using exact policy names from upgrade)
    policies = [
        ('asset_photos', 'Users can view asset photos for their assets'),
        ('asset_photos', 'Users can insert asset photos for their assets'),
        ('asset_photos', 'Users can update asset photos for their assets'),
        ('asset_photos', 'Users can delete asset photos for their assets'),
        ('asset_documents', 'Users can view asset documents for their assets'),
        ('asset_documents', 'Users can insert asset documents for their assets'),
        ('asset_documents', 'Users can update asset documents for their assets'),
        ('asset_documents', 'Users can delete asset documents for their assets'),
        ('asset_appraisals', 'Users can view asset appraisals for their assets'),
        ('asset_appraisals', 'Users can insert asset appraisals for their assets'),
        ('asset_appraisals', 'Users can update asset appraisals for their assets'),
        ('asset_appraisals', 'Users can delete asset appraisals for their assets'),
        ('asset_sale_requests', 'Users can view asset sale requests for their assets'),
        ('asset_sale_requests', 'Users can insert asset sale requests for their assets'),
        ('asset_sale_requests', 'Users can update asset sale requests for their assets'),
        ('asset_sale_requests', 'Users can delete asset sale requests for their assets'),
        ('asset_transfers', 'Users can view asset transfers for their assets'),
        ('asset_transfers', 'Users can insert asset transfers for their assets'),
        ('asset_transfers', 'Users can update asset transfers for their assets'),
        ('asset_transfers', 'Users can delete asset transfers for their assets'),
        ('asset_shares', 'Users can view asset shares for their assets'),
        ('asset_shares', 'Users can insert asset shares for their assets'),
        ('asset_shares', 'Users can update asset shares for their assets'),
        ('asset_shares', 'Users can delete asset shares for their assets'),
        ('asset_reports', 'Users can view asset reports for their assets'),
        ('asset_reports', 'Users can insert asset reports for their assets'),
        ('asset_reports', 'Users can update asset reports for their assets'),
        ('asset_reports', 'Users can delete asset reports for their assets'),
        ('asset_categories', 'Authenticated users can view asset categories'),
    ]
    
    for table, policy_name in policies:
        op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON {table};')
    
    # Disable RLS on all asset-related tables
    asset_tables = [
        'asset_photos',
        'asset_documents',
        'asset_appraisals',
        'asset_sale_requests',
        'asset_transfers',
        'asset_shares',
        'asset_reports',
        'asset_categories',
    ]
    
    for table in asset_tables:
        op.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;')
