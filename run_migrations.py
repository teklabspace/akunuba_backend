"""Run database migrations with detailed output"""
import sys
import os
from alembic import command
from alembic.config import Config

print("="*60)
print("Running Database Migrations")
print("="*60)
print()

try:
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Environment variables loaded")
except:
    print("⚠️  python-dotenv not available, using system env vars")

try:
    # Check database URL
    from app.config import settings
    db_url = settings.DATABASE_URL
    if db_url:
        # Mask password in URL for display
        if "@" in db_url:
            parts = db_url.split("@")
            if ":" in parts[0]:
                user_pass = parts[0].split("://")[1]
                if ":" in user_pass:
                    user = user_pass.split(":")[0]
                    db_url_display = db_url.replace(user_pass, f"{user}:***")
                else:
                    db_url_display = db_url
            else:
                db_url_display = db_url
        else:
            db_url_display = db_url
        print(f"✅ Database URL configured: {db_url_display[:80]}...")
    else:
        print("❌ ERROR: DATABASE_URL not set in environment variables")
        print("   Please set DATABASE_URL in your .env file")
        sys.exit(1)
except Exception as e:
    print(f"❌ ERROR loading configuration: {e}")
    sys.exit(1)

print()
print("Running migrations...")
print("-"*60)

try:
    # Create Alembic config
    alembic_cfg = Config("alembic.ini")
    
    # Run migrations
    command.upgrade(alembic_cfg, "head")
    
    print()
    print("="*60)
    print("✅ Migrations completed successfully!")
    print("="*60)
    print()
    print("You can now view tables in Supabase:")
    print("https://supabase.com/dashboard/project/ajodaszmvcowcnvdmszm/editor")
    print()
    
except Exception as e:
    print()
    print("="*60)
    print(f"❌ Migration failed: {e}")
    print("="*60)
    print()
    print("Common issues:")
    print("1. DATABASE_URL not set or incorrect")
    print("2. Database password incorrect")
    print("3. Database connection timeout")
    print("4. Tables already exist (try: python -m alembic downgrade -1)")
    print()
    import traceback
    traceback.print_exc()
    sys.exit(1)

