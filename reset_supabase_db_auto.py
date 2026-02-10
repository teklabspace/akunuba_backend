#!/usr/bin/env python3
"""
Auto Reset Supabase Database Script (Non-Interactive)

This script automatically resets your Supabase database without prompts.
WARNING: This will delete ALL data. Use with caution!

Usage:
    python reset_supabase_db_auto.py [method]
    
Methods:
    truncate  - Truncate all tables (removes data, keeps structure) [default]
    drop      - Drop and recreate all tables
    list      - Just list tables (safe)
"""

import asyncio
import sys
from app.config import settings
from app.database import engine, Base
from sqlalchemy import text
from app.utils.logger import logger


async def get_all_tables(conn):
    """Get all user tables from the database"""
    query = """
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """
    result = await conn.execute(text(query))
    rows = result.fetchall()
    return [row[0] for row in rows]


async def truncate_all_tables():
    """Truncate all tables (removes data, keeps structure)"""
    print("\n" + "="*60)
    print("TRUNCATING ALL TABLES (keeps structure)")
    print("="*60)
    
    try:
        async with engine.begin() as conn:
            # Get all tables
            tables = await get_all_tables(conn)
            print(f"\nFound {len(tables)} tables:")
            for table in tables:
                print(f"  - {table}")
            
            print("\n[INFO] Truncating tables...")
            
            # Disable foreign key checks temporarily
            await conn.execute(text("SET session_replication_role = 'replica';"))
            
            # Truncate tables in reverse order (respecting foreign keys)
            for table in reversed(tables):
                try:
                    await conn.execute(text(f'TRUNCATE TABLE "{table}" CASCADE;'))
                    print(f"  [OK] Truncated: {table}")
                except Exception as e:
                    print(f"  [ERROR] Error truncating {table}: {e}")
            
            # Re-enable foreign key checks
            await conn.execute(text("SET session_replication_role = 'origin';"))
            
            print("\n[SUCCESS] All tables truncated successfully!")
            
            # Verify
            print("\n[VERIFY] Verifying (all should be 0):")
            for table in tables:
                try:
                    result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table}";'))
                    count = result.scalar()
                    status = "[OK]" if count == 0 else "[FAIL]"
                    print(f"  {status} {table}: {count} rows")
                except:
                    print(f"  [?] {table}: (error checking)")
            
    except Exception as e:
        logger.error(f"Error truncating tables: {e}", exc_info=True)
        print(f"\n[ERROR] Error: {e}")
        raise


async def drop_and_recreate_tables():
    """Drop all tables and recreate them"""
    print("\n" + "="*60)
    print("DROPPING AND RECREATING ALL TABLES")
    print("="*60)
    
    try:
        async with engine.begin() as conn:
            # Get all tables
            tables = await get_all_tables(conn)
            print(f"\nFound {len(tables)} tables to drop")
            
            print("\n[INFO] Dropping all tables...")
            
            # Drop all tables
            await conn.execute(text("DROP SCHEMA public CASCADE;"))
            await conn.execute(text("CREATE SCHEMA public;"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO postgres;"))
            await conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
            
            print("  [OK] Dropped all tables")
            
            print("\n[INFO] Creating tables from models...")
            
            # Create all tables from models
            await conn.run_sync(Base.metadata.create_all)
            
            print("  [OK] Created all tables from models")
            
            print("\n[SUCCESS] Database reset and recreated successfully!")
            
    except Exception as e:
        logger.error(f"Error dropping/recreating tables: {e}", exc_info=True)
        print(f"\n[ERROR] Error: {e}")
        raise


async def list_tables():
    """List all tables in the database"""
    print("\n" + "="*60)
    print("LISTING ALL TABLES")
    print("="*60)
    
    try:
        async with engine.connect() as conn:
            tables = await get_all_tables(conn)
            
            print(f"\nFound {len(tables)} tables:\n")
            for i, table in enumerate(tables, 1):
                # Get row count
                try:
                    result = await conn.execute(text(f'SELECT COUNT(*) FROM "{table}";'))
                    count = result.scalar()
                    print(f"  {i:2d}. {table:30s} ({count:,} rows)")
                except:
                    print(f"  {i:2d}. {table:30s} (error getting count)")
            
            print()
            
    except Exception as e:
        logger.error(f"Error listing tables: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")


async def main():
    """Main function"""
    method = sys.argv[1] if len(sys.argv) > 1 else "truncate"
    
    print("\n" + "="*60)
    print("SUPABASE DATABASE RESET TOOL (AUTO MODE)")
    print("="*60)
    print(f"\nDatabase: {settings.DATABASE_URL[:50]}...")
    print(f"Environment: {settings.APP_ENV}")
    print(f"Method: {method}")
    
    if method == "truncate":
        await truncate_all_tables()
    elif method == "drop":
        await drop_and_recreate_tables()
    elif method == "list":
        await list_tables()
    else:
        print(f"\n[ERROR] Unknown method: {method}")
        print("\nAvailable methods:")
        print("  truncate  - Truncate all tables (removes data, keeps structure)")
        print("  drop      - Drop and recreate all tables")
        print("  list      - Just list tables (safe)")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n[WARNING] Operation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL ERROR] Fatal error: {e}")
        logger.error(f"Fatal error in reset script: {e}", exc_info=True)
        sys.exit(1)
