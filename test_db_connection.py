"""Test database connection"""
import asyncio
import asyncpg

async def test_connection():
    # Use pooler connection
    conn_str = "postgresql://postgres.ajodaszmvcowcnvdmszm:LaIWA4MTDVagKXJk@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    
    print("Attempting to connect to database...")
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(conn_str),
            timeout=15.0
        )
        print("Connected successfully!")
        
        # Check users table columns
        columns = await conn.fetch("""
            SELECT column_name, data_type FROM information_schema.columns 
            WHERE table_name = 'users' AND table_schema = 'public'
            ORDER BY ordinal_position
        """)
        print(f"\nUsers table columns:")
        for c in columns:
            print(f"  - {c['column_name']}: {c['data_type']}")
        
        await conn.close()
    except asyncio.TimeoutError:
        print("Connection timed out")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
