"""Enable RLS on alembic_version table"""
import sys
from sqlalchemy import create_engine, text
from app.config import settings

print("Enabling RLS on alembic_version table...")

try:
    # Get database URL and convert to sync format
    db_url = settings.DATABASE_URL
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    
    # Create engine
    engine = create_engine(db_url)
    
    # Enable RLS
    with engine.begin() as conn:
        result = conn.execute(text("ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY;"))
        print(f"   Executed: ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY")
    
    print("✅ RLS enabled on alembic_version table successfully!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

