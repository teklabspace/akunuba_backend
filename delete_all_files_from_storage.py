"""
Script to delete all files from Supabase Storage buckets (images and documents).
This will delete all files from both buckets.
"""

import asyncio
import sys
from app.integrations.supabase_client import SupabaseClient
from app.utils.logger import logger


def delete_all_files_from_bucket(bucket_name: str):
    """Delete all files from a specific bucket"""
    try:
        client = SupabaseClient.get_client()
        if not client:
            logger.error("Failed to get Supabase client")
            return 0
        
        logger.info(f"Listing files in '{bucket_name}' bucket...")
        deleted_count = 0
        
        def delete_folder_recursive(folder_path=""):
            """Recursively list and delete files in a folder"""
            nonlocal deleted_count
            try:
                # List items in current folder
                items = client.storage.from_(bucket_name).list(folder_path)
                
                if not items:
                    return
                
                file_paths = []
                
                for item in items:
                    # Construct full path
                    if folder_path:
                        item_path = f"{folder_path}/{item['name']}"
                    else:
                        item_path = item['name']
                    
                    # Check if it's a file (has metadata) or folder (no metadata or id)
                    # Files typically have 'id' and 'metadata' fields
                    if 'id' in item or (item.get('metadata') and 'size' in item.get('metadata', {})):
                        # It's a file
                        file_paths.append(item_path)
                    else:
                        # It's a folder, recurse into it
                        delete_folder_recursive(item_path)
                
                # Delete all files in current folder
                if file_paths:
                    logger.info(f"Found {len(file_paths)} files in '{folder_path or 'root'}' to delete")
                    
                    # Delete in batches (Supabase allows up to 1000 per batch)
                    batch_size = 100
                    for i in range(0, len(file_paths), batch_size):
                        batch = file_paths[i:i + batch_size]
                        try:
                            client.storage.from_(bucket_name).remove(batch)
                            deleted_count += len(batch)
                            if deleted_count % 50 == 0:
                                logger.info(f"Deleted {deleted_count} files from '{bucket_name}' bucket...")
                        except Exception as e:
                            logger.error(f"Failed to delete batch: {e}")
                            # Try deleting individually
                            for file_path in batch:
                                try:
                                    client.storage.from_(bucket_name).remove([file_path])
                                    deleted_count += 1
                                except Exception as e2:
                                    logger.warning(f"Failed to delete {file_path}: {e2}")
            
            except Exception as e:
                logger.warning(f"Error processing folder '{folder_path}': {e}")
        
        # Start recursive deletion from root
        delete_folder_recursive("")
        
        logger.info(f"Successfully deleted {deleted_count} files from '{bucket_name}' bucket")
        return deleted_count
            
    except Exception as e:
        logger.error(f"Error deleting files from '{bucket_name}' bucket: {e}", exc_info=True)
        return 0


def delete_all_files():
    """Delete all files from both images and documents buckets"""
    
    logger.info("=" * 50)
    logger.info("Starting file deletion from Supabase Storage")
    logger.info("=" * 50)
    
    # Delete from images bucket
    logger.info("\n🗑️  Deleting files from 'images' bucket...")
    images_deleted = delete_all_files_from_bucket("images")
    
    # Delete from documents bucket
    logger.info("\n🗑️  Deleting files from 'documents' bucket...")
    documents_deleted = delete_all_files_from_bucket("documents")
    
    logger.info("\n" + "=" * 50)
    logger.info("Summary:")
    logger.info(f"  - Files deleted from 'images' bucket: {images_deleted}")
    logger.info(f"  - Files deleted from 'documents' bucket: {documents_deleted}")
    logger.info(f"  - Total files deleted: {images_deleted + documents_deleted}")
    logger.info("=" * 50)
    logger.info("File deletion completed!")


if __name__ == "__main__":
    print("=" * 50)
    print("WARNING: This will delete ALL files from Supabase Storage buckets!")
    print("This will delete files from:")
    print("  - 'images' bucket")
    print("  - 'documents' bucket")
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
            delete_all_files()
            print("\nDeletion completed successfully!")
        except Exception as e:
            print(f"\nError: {e}")
            sys.exit(1)
    else:
        print("\nDeletion cancelled.")
        sys.exit(0)
