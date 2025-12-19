"""Check and install missing packages"""
import subprocess
import sys

missing_packages = []

# Check alpaca
try:
    import alpaca
    print("✅ alpaca-trade-api installed")
except ImportError:
    print("❌ alpaca-trade-api MISSING")
    missing_packages.append("alpaca-trade-api==3.1.1")

# Check plaid
try:
    import plaid
    print("✅ plaid-python installed")
except ImportError:
    print("❌ plaid-python MISSING")
    missing_packages.append("plaid-python==9.0.0")

# Check other critical packages
packages_to_check = [
    ("stripe", "stripe==7.0.0"),
    ("supabase", "supabase==2.0.0"),
    ("posthog", "posthog==3.0.0"),
    ("sendbird", "sendbird-platform-sdk==2.1.1"),
]

for module_name, package_name in packages_to_check:
    try:
        __import__(module_name)
        print(f"✅ {package_name.split('==')[0]} installed")
    except ImportError:
        print(f"❌ {package_name.split('==')[0]} MISSING")
        missing_packages.append(package_name)

if missing_packages:
    print(f"\n📦 Installing {len(missing_packages)} missing packages...")
    for package in missing_packages:
        print(f"   Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    print("\n✅ All packages installed!")
else:
    print("\n✅ All packages are installed!")

print("\nTesting imports...")
try:
    from app.main import app
    print(f"✅ Server app loaded successfully with {len(app.routes)} routes!")
except Exception as e:
    print(f"❌ Error loading app: {e}")
    import traceback
    traceback.print_exc()

