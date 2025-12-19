"""Direct SQL script to add missing columns to kyb_verifications table"""
import asyncio
import asyncpg
from app.config import settings
import os
from dotenv import load_dotenv

load_dotenv()

async def add_columns():
    """Add missing columns directly using SQL"""
    # Get database URL from settings
    database_url = settings.DATABASE_URL
    
    # Parse the connection string
    # Format: postgresql+asyncpg://user:password@host:port/database
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "")
    
    # Extract connection details
    # Format: user:password@host:port/database
    parts = database_url.split("@")
    if len(parts) != 2:
        print("❌ Invalid database URL format")
        return False
    
    auth = parts[0].split(":")
    if len(auth) != 2:
        print("❌ Invalid database credentials format")
        return False
    
    user = auth[0]
    password = auth[1]
    
    host_port_db = parts[1].split("/")
    if len(host_port_db) != 2:
        print("❌ Invalid database host/port/database format")
        return False
    
    host_port = host_port_db[0].split(":")
    host = host_port[0]
    port = int(host_port[1]) if len(host_port) > 1 else 5432
    database = host_port_db[1]
    
    print("=" * 70)
    print("Adding Missing Columns to kyb_verifications Table")
    print("=" * 70)
    print(f"Connecting to: {host}:{port}/{database}")
    print()
    
    try:
        # Connect to database
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database
        )
        
        print("✅ Connected to database")
        
        # Check if columns already exist
        check_query = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'kyb_verifications' 
        AND column_name IN ('ownership_structure', 'beneficial_owners');
        """
        
        existing_columns = await conn.fetch(check_query)
        existing_names = [row['column_name'] for row in existing_columns]
        
        print(f"\nExisting columns: {existing_names}")
        
        # Add ownership_structure if it doesn't exist
        if 'ownership_structure' not in existing_names:
            print("\nAdding 'ownership_structure' column...")
            await conn.execute("""
                ALTER TABLE kyb_verifications 
                ADD COLUMN IF NOT EXISTS ownership_structure JSONB;
            """)
            print("✅ Added 'ownership_structure' column")
        else:
            print("✅ 'ownership_structure' column already exists")
        
        # Add beneficial_owners if it doesn't exist
        if 'beneficial_owners' not in existing_names:
            print("\nAdding 'beneficial_owners' column...")
            await conn.execute("""
                ALTER TABLE kyb_verifications 
                ADD COLUMN IF NOT EXISTS beneficial_owners JSONB;
            """)
            print("✅ Added 'beneficial_owners' column")
        else:
            print("✅ 'beneficial_owners' column already exists")
        
        # Verify columns were added
        final_check = await conn.fetch(check_query)
        final_names = [row['column_name'] for row in final_check]
        
        print("\n" + "=" * 70)
        if 'ownership_structure' in final_names and 'beneficial_owners' in final_names:
            print("✅ SUCCESS! Both columns are now in the database")
            print("=" * 70)
            await conn.close()
            return True
        else:
            print("❌ Some columns are still missing")
            print(f"Columns found: {final_names}")
            print("=" * 70)
            await conn.close()
            return False
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        print("=" * 70)
        return False


if __name__ == "__main__":
    print("\n")
    success = asyncio.run(add_columns())
    print("\n")
    exit(0 if success else 1)

