try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    create_client = None
    Client = None

from typing import Optional
from app.config import settings
from app.utils.logger import logger


class SupabaseClient:
    _instance: Client = None

    @classmethod
    def get_client(cls) -> Optional[Client]:
        if not SUPABASE_AVAILABLE:
            logger.warning("Supabase SDK not installed. Install with: pip install supabase")
            return None
        if cls._instance is None:
            try:
                cls._instance = create_client(
                    settings.SUPABASE_URL,
                    settings.SUPABASE_SERVICE_ROLE_KEY
                )
                logger.info("Supabase client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                raise
        return cls._instance

    @classmethod
    def upload_file(cls, bucket: str, file_path: str, file_data: bytes, content_type: str = "application/octet-stream", upsert: bool = True) -> str:
        client = cls.get_client()
        try:
            # Supabase Python client - file_options should only contain string values
            # The upsert parameter should be passed separately or as a string, not as a boolean in file_options
            file_options = {"content-type": content_type}
            
            # Try to upload - if upsert is needed, handle duplicates separately
            # Some Supabase client versions don't support upsert in file_options
            try:
                response = client.storage.from_(bucket).upload(
                    file_path,
                    file_data,
                    file_options=file_options
                )
            except Exception as upload_error:
                # If upload fails due to duplicate and upsert is True, try to delete and re-upload
                if upsert and ("already exists" in str(upload_error).lower() or "duplicate" in str(upload_error).lower()):
                    logger.warning(f"File exists, attempting to overwrite: {file_path}")
                    try:
                        cls.delete_file(bucket, file_path)
                        response = client.storage.from_(bucket).upload(
                            file_path,
                            file_data,
                            file_options=file_options
                        )
                    except Exception as retry_error:
                        logger.error(f"Failed to overwrite file: {retry_error}")
                        raise
                else:
                    raise
            if isinstance(response, dict):
                return response.get("path", file_path)
            return file_path
        except Exception as e:
            error_str = str(e)
            # Check if it's a duplicate error
            if "already exists" in error_str.lower() or "duplicate" in error_str.lower():
                logger.warning(f"File already exists at {file_path}, attempting overwrite")
                # Try to delete first, then upload
                try:
                    cls.delete_file(bucket, file_path)
                    response = client.storage.from_(bucket).upload(
                        file_path,
                        file_data,
                        file_options=file_options
                    )
                    if isinstance(response, dict):
                        return response.get("path", file_path)
                    return file_path
                except Exception as delete_error:
                    logger.error(f"Failed to overwrite existing file: {delete_error}")
                    raise
            # Check for header value error (boolean in header)
            if "Header value must be str or bytes" in error_str or "not <class 'bool'>" in error_str:
                logger.error(f"Supabase client header error - this may be a client library issue: {e}")
                # Try without file_options to see if that helps
                try:
                    response = client.storage.from_(bucket).upload(
                        file_path,
                        file_data
                    )
                    if isinstance(response, dict):
                        return response.get("path", file_path)
                    return file_path
                except Exception as fallback_error:
                    logger.error(f"Failed to upload even without file_options: {fallback_error}")
                    raise
            logger.error(f"Failed to upload file to Supabase Storage: {e}")
            raise

    @classmethod
    def get_file_url(cls, bucket: str, file_path: str) -> str:
        """
        Get public URL for a file in Supabase storage.
        Returns absolute URL that can be accessed from anywhere (if bucket is public).
        
        IMPORTANT: The 'documents' bucket must be set to PUBLIC in Supabase Storage settings
        for these URLs to be accessible without authentication.
        
        Returns format: https://<project-id>.supabase.co/storage/v1/object/public/<bucket>/<file_path>
        """
        client = cls.get_client()
        try:
            response = client.storage.from_(bucket).get_public_url(file_path)
            if isinstance(response, dict):
                public_url = response.get("publicUrl", "")
            else:
                public_url = str(response) if response else ""
            
            # Ensure URL is absolute (starts with https://)
            if public_url and not public_url.startswith(('http://', 'https://')):
                # If somehow not absolute, construct from SUPABASE_URL
                if public_url.startswith('/'):
                    public_url = f"{settings.SUPABASE_URL}{public_url}"
                else:
                    public_url = f"{settings.SUPABASE_URL}/storage/v1/object/public/{bucket}/{file_path}"
            
            # Remove trailing query params if empty (e.g., trailing "?")
            if public_url and public_url.endswith('?'):
                public_url = public_url.rstrip('?')
            
            return public_url
        except Exception as e:
            logger.error(f"Failed to get file URL from Supabase Storage: {e}")
            raise

    @classmethod
    def delete_file(cls, bucket: str, file_path: str) -> bool:
        client = cls.get_client()
        try:
            response = client.storage.from_(bucket).remove([file_path])
            # Check if deletion was successful
            if isinstance(response, list) and len(response) > 0:
                return True
            return True  # Assume success if no error
        except Exception as e:
            logger.error(f"Failed to delete file from Supabase Storage: {e}")
            return False
    
    @classmethod
    def download_file(cls, bucket: str, file_path: str) -> bytes:
        """Download a file from Supabase Storage"""
        client = cls.get_client()
        try:
            response = client.storage.from_(bucket).download(file_path)
            if isinstance(response, bytes):
                return response
            elif isinstance(response, dict):
                # Some Supabase clients return dict with data
                return response.get("data", b"")
            return b""
        except Exception as e:
            logger.error(f"Failed to download file from Supabase Storage: {e}")
            raise
    
    @classmethod
    def list_files(cls, bucket: str, folder: str = "") -> list:
        """List files in a bucket/folder"""
        client = cls.get_client()
        try:
            response = client.storage.from_(bucket).list(folder)
            if isinstance(response, list):
                return response
            return []
        except Exception as e:
            logger.error(f"Failed to list files from Supabase Storage: {e}")
            return []

