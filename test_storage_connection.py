"""
Quick test script to verify Supabase Storage connection and bucket access
Run this after creating the 'documents' bucket to verify everything works.
"""
import sys
from app.integrations.supabase_client import SupabaseClient
from app.utils.logger import logger

def test_storage_connection():
    """Test Supabase Storage connection and bucket access"""
    print("=" * 60)
    print("Testing Supabase Storage Connection")
    print("=" * 60)
    
    try:
        # Test 1: Initialize client
        print("\n1. Testing client initialization...")
        client = SupabaseClient.get_client()
        if client:
            print("   ✅ Supabase client initialized successfully")
        else:
            print("   ❌ Failed to initialize Supabase client")
            return False
        
        # Test 2: List files in documents bucket
        print("\n2. Testing bucket access...")
        try:
            files = SupabaseClient.list_files("documents")
            print(f"   ✅ Can access 'documents' bucket")
            print(f"   📁 Files/folders found: {len(files)}")
            if files:
                print(f"   📄 Sample items: {files[:3]}")
        except Exception as e:
            print(f"   ❌ Cannot access 'documents' bucket: {e}")
            print("   💡 Make sure:")
            print("      - Bucket name is exactly 'documents'")
            print("      - Bucket exists in Supabase Storage")
            print("      - SUPABASE_SERVICE_ROLE_KEY is correct")
            return False
        
        # Test 3: Test upload capability (dry run - no actual upload)
        print("\n3. Testing upload capability...")
        try:
            # Just verify the client has the upload method
            if hasattr(client.storage.from_("documents"), 'upload'):
                print("   ✅ Upload method available")
            else:
                print("   ❌ Upload method not available")
                return False
        except Exception as e:
            print(f"   ❌ Error checking upload capability: {e}")
            return False
        
        # Test 4: Verify environment variables
        print("\n4. Checking environment configuration...")
        from app.config import settings
        if settings.SUPABASE_URL:
            print(f"   ✅ SUPABASE_URL is set")
        else:
            print("   ❌ SUPABASE_URL is not set")
            return False
            
        if settings.SUPABASE_SERVICE_ROLE_KEY:
            # Mask the key for security
            masked_key = settings.SUPABASE_SERVICE_ROLE_KEY[:20] + "..." if len(settings.SUPABASE_SERVICE_ROLE_KEY) > 20 else "***"
            print(f"   ✅ SUPABASE_SERVICE_ROLE_KEY is set ({masked_key})")
        else:
            print("   ❌ SUPABASE_SERVICE_ROLE_KEY is not set")
            return False
        
        print("\n" + "=" * 60)
        print("✅ All tests passed! Storage is ready to use.")
        print("=" * 60)
        print("\n💡 Next steps:")
        print("   1. Set up RLS policies (run setup_storage_policies.sql)")
        print("   2. Test file upload via API endpoint")
        print("   3. Check files in Supabase Storage dashboard")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        logger.error(f"Storage connection test failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_storage_connection()
    sys.exit(0 if success else 1)
