"""Check migration status and test database connection"""
import sys

print("="*60)
print("Migration Status Check")
print("="*60)
print()

# Test imports
try:
    print("1. Testing imports...")
    from app.config import settings
    print("   ✅ Config loaded")
    
    from app.database import engine
    print("   ✅ Database engine imported")
    
    from alembic.config import Config
    from alembic import command
    print("   ✅ Alembic imported")
except Exception as e:
    print(f"   ❌ Import error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Check database URL
print("\n2. Checking database configuration...")
try:
    db_url = settings.DATABASE_URL
    if not db_url:
        print("   ❌ DATABASE_URL is not set!")
        print("   Please set it in your .env file")
        sys.exit(1)
    
    # Mask password
    if "@" in db_url:
        masked = db_url.split("@")[0].split("://")[0] + "://***@" + db_url.split("@")[1]
    else:
        masked = db_url[:50] + "..."
    
    print(f"   ✅ DATABASE_URL is set: {masked}")
    
    # Check if it's asyncpg format
    if db_url.startswith("postgresql+asyncpg://"):
        print("   ✅ Using asyncpg format (will be converted for migrations)")
    elif db_url.startswith("postgresql://"):
        print("   ✅ Using standard postgresql format")
    else:
        print(f"   ⚠️  Unexpected database URL format: {db_url[:30]}...")
        
except Exception as e:
    print(f"   ❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Check migration files
print("\n3. Checking migration files...")
import os
migration_dir = "alembic/versions"
if os.path.exists(migration_dir):
    migrations = [f for f in os.listdir(migration_dir) if f.endswith(".py") and f != "__pycache__"]
    print(f"   ✅ Found {len(migrations)} migration file(s)")
    for m in migrations:
        print(f"      - {m}")
else:
    print("   ❌ Migration directory not found!")
    sys.exit(1)

# Try to get current revision
print("\n4. Checking current database state...")
try:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine, text
    
    # Create sync engine for checking
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url)
    
    with engine.connect() as conn:
        # Check if alembic_version table exists
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'alembic_version'
            );
        """))
        has_version_table = result.scalar()
        
        if has_version_table:
            result = conn.execute(text("SELECT version_num FROM alembic_version"))
            current_version = result.scalar()
            print(f"   ✅ Database has migrations table")
            print(f"   ✅ Current version: {current_version}")
        else:
            print("   ℹ️  No migrations table found (database is empty)")
            print("   ✅ Ready to run initial migration")
        
        # Check if any tables exist
        result = conn.execute(text("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
        """))
        table_count = result.scalar()
        print(f"   ℹ️  Found {table_count} table(s) in database")
        
except Exception as e:
    print(f"   ⚠️  Could not check database state: {e}")
    print("   This might be a connection issue")

print("\n" + "="*60)
print("Ready to run migrations!")
print("="*60)
print("\nRun: python -m alembic upgrade head")
print("Or: python run_migrations.py")
print()

