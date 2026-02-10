"""Test Supabase connection via REST API"""
import httpx
import asyncio

SUPABASE_URL = "https://ajodaszmvcowcnvdmszm.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFqb2Rhc3ptdmNvd2NudmRtc3ptIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MzE3ODExOCwiZXhwIjoyMDc4NzU0MTE4fQ.zbkb9ElVEKbT9C55Vgg7Af56LDya3RWC1vsxRMA1OnY"

async def test_supabase():
    print("Testing Supabase REST API connection...")
    
    async with httpx.AsyncClient() as client:
        # Test health
        try:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}"
                },
                timeout=10.0
            )
            print(f"REST API Status: {response.status_code}")
        except Exception as e:
            print(f"REST API Error: {e}")
        
        # Check users table
        try:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/users?select=*&limit=1",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}"
                },
                timeout=10.0
            )
            print(f"Users table query: {response.status_code}")
            if response.status_code == 200:
                print(f"Response: {response.text[:500]}")
            else:
                print(f"Error: {response.text}")
        except Exception as e:
            print(f"Users query error: {e}")

if __name__ == "__main__":
    asyncio.run(test_supabase())
