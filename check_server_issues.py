"""Quick diagnostic script to check server startup issues"""
import sys
import traceback

print("="*60)
print("Checking Server Startup Issues")
print("="*60)

# Test 1: Check config
print("\n1. Testing config import...")
try:
    from app.config import settings
    print("   ✅ Config loaded")
    print(f"   DATABASE_URL: {'Set' if settings.DATABASE_URL else 'NOT SET'}")
except Exception as e:
    print(f"   ❌ Config error: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 2: Check database connection
print("\n2. Testing database connection...")
try:
    from app.database import engine
    print("   ✅ Database engine created")
except Exception as e:
    print(f"   ❌ Database error: {e}")
    traceback.print_exc()

# Test 3: Check API imports
print("\n3. Testing API imports...")
try:
    from app.api.v1 import auth, users, accounts
    print("   ✅ Basic API imports OK")
except Exception as e:
    print(f"   ❌ API import error: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 4: Check scheduler
print("\n4. Testing scheduler import...")
try:
    from app.core.scheduler import scheduler
    print("   ✅ Scheduler imported")
except Exception as e:
    print(f"   ⚠️  Scheduler error (may be OK): {e}")

# Test 5: Try to create app
print("\n5. Testing FastAPI app creation...")
try:
    from app.main import app
    print("   ✅ FastAPI app created successfully!")
    print(f"   App title: {app.title}")
    print(f"   Routes count: {len(app.routes)}")
except Exception as e:
    print(f"   ❌ App creation error: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*60)
print("✅ All checks passed! Server should start normally.")
print("="*60)
print("\nTry starting server with:")
print("python -m uvicorn app.main:app --host 0.0.0.0 --port 8000")

