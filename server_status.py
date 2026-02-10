"""Check server status and port"""
import requests
import sys

try:
    # Try health endpoint
    r = requests.get('http://localhost:8000/health', timeout=2)
    print(f"✅ Server is RUNNING on port 8000")
    print(f"✅ Health check: {r.status_code} - {r.json()}")
    print(f"\n📍 Server URL: http://localhost:8000")
    print(f"📍 API Base URL: http://localhost:8000/api/v1")
    print(f"📍 Health Check: http://localhost:8000/health")
    sys.exit(0)
except requests.exceptions.Timeout:
    print("⚠️  Server is running on port 8000 but not responding (likely database connection issue)")
    print(f"\n📍 Server Port: 8000")
    print(f"📍 Server URL: http://localhost:8000")
    print(f"📍 API Base URL: http://localhost:8000/api/v1")
    sys.exit(1)
except requests.exceptions.ConnectionError:
    print("❌ Server is NOT running on port 8000")
    sys.exit(1)
except Exception as e:
    print(f"⚠️  Error checking server: {e}")
    print(f"\n📍 Server Port: 8000 (configured)")
    sys.exit(1)
