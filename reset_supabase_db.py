#!/usr/bin/env python3
"""
Reset Supabase Database Script

This script provides multiple methods to reset your Supabase database:
1. Truncate all tables (removes data, keeps structure)
2. Drop and recreate all tables (removes data and structure, then recreates)
3. List all tables

WARNING: This will delete ALL data in your database. Use with caution!
"""

import asyncio
import asyncpg
from app.config import settings
from app.database import engine, Base
from sqlalchemy import text, inspect
from app.models import (
    User, Account, Asset, AssetValuation, AssetOwnership, Portfolio,
    Order, OrderHistory, MarketplaceListing, Offer, EscrowTransaction,
    Payment, Refund, Invoice, Subscription, LinkedAccount, Transaction,
    Document, SupportTicket, Notification, KYCVerification, KYBVerification,
    JointAccountInvitation, TicketReply
)
from app.utils.logger import logger


# List of all tables in order (respecting foreign key constraints)
# Tables with foreign keys should be deleted first
TABLES_ORDER = [
    # Tables with foreign keys (delete first)
    "ticket_replies",
    "notifications",
    "transactions",
    "linked_accounts",
    "subscriptions",
    "invoices",
    "refunds",
    "payments",
    "escrow_transactions",
    "offers",
    "marketplace_listings",
    "order_histories",
    "orders",
    "asset_valuations",
    "asset_ownerships",
    "assets",
    "portfolios",
    "documents",
    "kyb_verifications",
    "kyc_verifications",
    "support_tickets",
    "joint_account_invitations",
    "accounts",
    "users",
    # System tables (if needed)
    "alembic_version",
]


async def get_all_tables(conn):
    """Get all user tables from the database"""
    query = """
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """
    rows = await conn.fetch(query)
    return [row['table_name'] for row in rows]


async def truncate_all_tables():
    """
    Method 1: Truncate all tables (removes data, keeps structure)
    This is faster and preserves table structure, indexes, etc.
    """
    print("\n" + "="*60)
    print("METHOD 1: Truncating all tables (keeps structure)")
    print("="*60)
    
    try:
        async with engine.connect() as conn:
            # Disable foreign key checks temporarily
            await conn.execute(text("SET session_replication_role = 'replica';"))
            
            # Get all tables
            tables = await get_all_tables(conn)
            print(f"\nFound {len(tables)} tables:")
            for table in tables:
                print(f"  - {table}")
            
            # Confirm
            response = input("\n⚠️  WARNING: This will delete ALL data from ALL tables!\n"
                            "Type 'YES' to continue, or anything else to cancel: ")
            
            if response != 'YES':
                print("❌ Operation cancelled.")
                return
            
            print("\n🔄 Truncating tables...")
            
            # Truncate tables in reverse order (respecting foreign keys)
            for table in reversed(tables):
                try:
                    await conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE;'))
                    print(f"  ✓ Truncated: {table}")
                except Exception as e:
                    print(f"  ✗ Error truncating {table}: {e}")
            
            # Re-enable foreign key checks
            await conn.execute(text("SET session_replication_role = 'origin';"))
            await conn.commit()
            
            print("\n✅ All tables truncated successfully!")
            
    except Exception as e:
        logger.error(f"Error truncating tables: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        raise


async def drop_and_recreate_tables():
    """
    Method 2: Drop all tables and recreate them
    This removes both data and structure, then recreates from models
    """
    print("\n" + "="*60)
    print("METHOD 2: Dropping and recreating all tables")
    print("="*60)
    
    try:
        async with engine.begin() as conn:
            # Get all tables
            tables = await get_all_tables(conn)
            print(f"\nFound {len(tables)} tables:")
            for table in tables:
                print(f"  - {table}")
            
            # Confirm
            response = input("\n⚠️  WARNING: This will DROP all tables and recreate them!\n"
                            "All data and structure will be lost!\n"
                            "Type 'YES' to continue, or anything else to cancel: ")
            
            if response != 'YES':
                print("❌ Operation cancelled.")
                return
            
            print("\n🔄 Dropping all tables...")
            
            # Drop all tables
            await conn.execute(text("DROP SCHEMA public CASCADE;"))
            await conn.execute(text("CREATE SCHEMA public;"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO postgres;"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
            
            print("  ✓ Dropped all tables")
            
            print("\n🔄 Creating tables from models...")
            
            # Create all tables from models
            async with engine.begin() as create_conn:
                await create_conn.run_sync(Base.metadata.create_all)
            
            print("  ✓ Created all tables from models")
            
            print("\n✅ Database reset and recreated successfully!")
            
    except Exception as e:
        logger.error(f"Error dropping/recreating tables: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        raise


async def list_tables():
    """List all tables in the database"""
    print("\n" + "="*60)
    print("Listing all tables in database")
    print("="*60)
    
    try:
        async with engine.connect() as conn:
            tables = await get_all_tables(conn)
            
            print(f"\nFound {len(tables)} tables:\n")
            for i, table in enumerate(tables, 1):
                # Get row count
                try:
                    count_result = await conn.execute(
                        text(f'SELECT COUNT(*) as count FROM "{table}";')
                    )
                    count = count_result.scalar()
                    print(f"  {i:2d}. {table:30s} ({count:,} rows)")
                except:
                    print(f"  {i:2d}. {table:30s} (error getting count)")
            
            print()
            
    except Exception as e:
        logger.error(f"Error listing tables: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")


async def reset_via_sql():
    """
    Method 3: Execute custom SQL to reset database
    """
    print("\n" + "="*60)
    print("METHOD 3: Custom SQL Reset")
    print("="*60)
    
    sql = """
    -- Disable foreign key checks
    SET session_replication_role = 'replica';
    
    -- Truncate all tables
    TRUNCATE TABLE 
        ticket_replies,
        notifications,
        transactions,
        linked_accounts,
        subscriptions,
        invoices,
        refunds,
        payments,
        escrow_transactions,
        offers,
        marketplace_listings,
        order_histories,
        orders,
        asset_valuations,
        asset_ownerships,
        assets,
        portfolios,
        documents,
        kyb_verifications,
        kyc_verifications,
        support_tickets,
        joint_account_invitations,
        accounts,
        users
    CASCADE;
    
    -- Re-enable foreign key checks
    SET session_replication_role = 'origin';
    """
    
    print("\nSQL to execute:")
    print("-" * 60)
    print(sql)
    print("-" * 60)
    
    response = input("\n⚠️  Execute this SQL? (yes/no): ")
    
    if response.lower() != 'yes':
        print("❌ Operation cancelled.")
        return
    
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql))
            print("\n✅ SQL executed successfully!")
            
    except Exception as e:
        logger.error(f"Error executing SQL: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        raise


async def main():
    """Main function"""
    print("\n" + "="*60)
    print("SUPABASE DATABASE RESET TOOL")
    print("="*60)
    print(f"\nDatabase URL: {settings.DATABASE_URL[:50]}...")
    print(f"Environment: {settings.APP_ENV}")
    
    print("\nSelect an option:")
    print("  1. List all tables (safe)")
    print("  2. Truncate all tables (removes data, keeps structure)")
    print("  3. Drop and recreate all tables (removes everything)")
    print("  4. Execute custom SQL reset")
    print("  5. Exit")
    
    choice = input("\nEnter your choice (1-5): ").strip()
    
    if choice == '1':
        await list_tables()
    elif choice == '2':
        await truncate_all_tables()
    elif choice == '3':
        await drop_and_recreate_tables()
    elif choice == '4':
        await reset_via_sql()
    elif choice == '5':
        print("\n👋 Exiting...")
        return
    else:
        print("\n❌ Invalid choice. Please run the script again.")
        return


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user.")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        logger.error(f"Fatal error in reset script: {e}", exc_info=True)
