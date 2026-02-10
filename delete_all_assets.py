"""
Script to delete all assets and uploaded images from database and storage.
This will:
1. Delete all photos from Supabase storage
2. Delete all asset documents from Supabase storage
3. Delete all assets from database (cascade will delete related records)
"""

import asyncio
import sys
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.integrations.supabase_client import SupabaseClient
from app.utils.logger import logger


async def delete_all_assets():
    """Delete all assets and their related files"""
    
    async with AsyncSessionLocal() as async_session:
        try:
            # Get all asset photos using raw SQL to avoid ORM relationship issues
            logger.info("Fetching all asset photos...")
            photos_result = await async_session.execute(text("""
                SELECT id, supabase_storage_path 
                FROM asset_photos 
                WHERE supabase_storage_path IS NOT NULL
            """))
            photos = photos_result.fetchall()
            logger.info(f"Found {len(photos)} photos to delete from storage")
            
            # Delete photos from Supabase storage
            deleted_photos = 0
            for photo_id, storage_path in photos:
                try:
                    if storage_path:
                        SupabaseClient.delete_file("documents", storage_path)
                        deleted_photos += 1
                        if deleted_photos % 10 == 0:
                            logger.info(f"Deleted {deleted_photos}/{len(photos)} photos from storage...")
                except Exception as e:
                    logger.warning(f"Failed to delete photo {photo_id} from storage: {e}")
            
            logger.info(f"Successfully deleted {deleted_photos} photos from storage")
            
            # Get all asset documents using raw SQL
            logger.info("Fetching all asset documents...")
            documents_result = await async_session.execute(text("""
                SELECT id, supabase_storage_path 
                FROM asset_documents 
                WHERE supabase_storage_path IS NOT NULL
            """))
            documents = documents_result.fetchall()
            logger.info(f"Found {len(documents)} documents to delete from storage")
            
            # Delete documents from Supabase storage
            deleted_docs = 0
            for doc_id, storage_path in documents:
                try:
                    if storage_path:
                        SupabaseClient.delete_file("documents", storage_path)
                        deleted_docs += 1
                        if deleted_docs % 10 == 0:
                            logger.info(f"Deleted {deleted_docs}/{len(documents)} documents from storage...")
                except Exception as e:
                    logger.warning(f"Failed to delete document {doc_id} from storage: {e}")
            
            logger.info(f"Successfully deleted {deleted_docs} documents from storage")
            
            # Get count of assets before deletion
            logger.info("Counting assets...")
            count_result = await async_session.execute(text("SELECT COUNT(*) FROM assets"))
            asset_count = count_result.scalar()
            logger.info(f"Found {asset_count} assets to delete")
            
            # Delete all related records first (due to foreign key constraints)
            logger.info("Deleting related records first...")
            
            # Delete in correct order to avoid foreign key violations
            related_tables = [
                "asset_valuations",
                "asset_ownership",
                "asset_photos",
                "asset_documents", 
                "asset_appraisals",
                "asset_sale_requests",
                "asset_transfers",
                "asset_shares",
                "asset_reports"
            ]
            
            for table in related_tables:
                logger.info(f"Deleting from {table}...")
                await async_session.execute(text(f"DELETE FROM {table}"))
            
            # Now delete all assets
            logger.info("Deleting all assets from database...")
            await async_session.execute(text("DELETE FROM assets"))
            await async_session.commit()
            logger.info(f"Successfully deleted {asset_count} assets and all related records from database")
            
            logger.info("=" * 50)
            logger.info("Summary:")
            logger.info(f"  - Photos deleted from storage: {deleted_photos}")
            logger.info(f"  - Documents deleted from storage: {deleted_docs}")
            logger.info(f"  - Assets deleted from database: {asset_count}")
            logger.info("=" * 50)
            logger.info("All assets and images have been deleted successfully!")
            
        except Exception as e:
            logger.error(f"Error deleting assets: {e}", exc_info=True)
            await async_session.rollback()
            raise
        finally:
            pass  # Session will close automatically with context manager


if __name__ == "__main__":
    print("=" * 50)
    print("WARNING: This will delete ALL assets and images!")
    print("This action cannot be undone.")
    print("=" * 50)
    
    # Check for --yes flag to skip confirmation
    skip_confirmation = "--yes" in sys.argv or "-y" in sys.argv
    
    if not skip_confirmation:
        try:
            response = input("\nAre you sure you want to continue? (yes/no): ").strip().lower()
        except EOFError:
            print("\nNon-interactive mode detected. Use --yes or -y flag to skip confirmation.")
            sys.exit(1)
    else:
        response = "yes"
        print("\nSkipping confirmation (--yes flag provided)")
    
    if response == "yes":
        print("\nStarting deletion...")
        try:
            asyncio.run(delete_all_assets())
            print("\nDeletion completed successfully!")
        except Exception as e:
            print(f"\nError: {e}")
            sys.exit(1)
    else:
        print("\nDeletion cancelled.")
        sys.exit(0)
