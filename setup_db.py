"""
Database setup script - drops all tables and recreates them
"""
import asyncio
import asyncpg

async def reset_database():
    conn_str = "postgresql://postgres:LaIWA4MTDVagKXJk@db.ajodaszmvcowcnvdmszm.supabase.co:5432/postgres"
    
    print("Connecting to database...")
    conn = await asyncpg.connect(conn_str)
    
    print("Dropping all existing tables...")
    
    # Drop tables in correct order (respecting foreign keys)
    tables_to_drop = [
        'notifications',
        'ticket_replies', 
        'support_tickets',
        'documents',
        'transactions',
        'linked_accounts',
        'subscriptions',
        'invoices',
        'refunds',
        'payments',
        'escrow_transactions',
        'offers',
        'marketplace_listings',
        'order_history',
        'orders',
        'portfolios',
        'asset_ownership',
        'asset_valuations',
        'assets',
        'kyb_verifications',
        'kyc_verifications',
        'joint_account_invitations',
        'accounts',
        'users',
        'alembic_version'
    ]
    
    for table in tables_to_drop:
        try:
            await conn.execute(f'DROP TABLE IF EXISTS {table} CASCADE')
            print(f"  Dropped: {table}")
        except Exception as e:
            print(f"  Error dropping {table}: {e}")
    
    # Drop all custom enum types
    print("\nDropping enum types...")
    enums = [
        'notificationtype', 'ticketpriority', 'ticketstatus', 'documenttype',
        'linkedaccounttype', 'subscriptionstatus', 'subscriptionplan',
        'paymentstatus', 'paymentmethod', 'escrowstatus', 'offerstatus',
        'listingstatus', 'orderstatus', 'ordertype', 'assettype',
        'kybstatus', 'kycstatus', 'invitationstatus', 'accounttype', 'role'
    ]
    for enum in enums:
        try:
            await conn.execute(f'DROP TYPE IF EXISTS {enum} CASCADE')
        except:
            pass
    
    print("\nDatabase cleared! Now run: python -m alembic upgrade head")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(reset_database())
