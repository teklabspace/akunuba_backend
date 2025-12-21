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
    def upload_file(cls, bucket: str, file_path: str, file_data: bytes, content_type: str = "application/octet-stream") -> str:
        client = cls.get_client()
        try:
            response = client.storage.from_(bucket).upload(
                file_path,
                file_data,
                file_options={"content-type": content_type, "upsert": "true"}
            )
            if isinstance(response, dict):
                return response.get("path", file_path)
            return file_path
        except Exception as e:
            logger.error(f"Failed to upload file to Supabase Storage: {e}")
            raise

    @classmethod
    def get_file_url(cls, bucket: str, file_path: str) -> str:
        client = cls.get_client()
        try:
            response = client.storage.from_(bucket).get_public_url(file_path)
            if isinstance(response, dict):
                return response.get("publicUrl", "")
            return str(response) if response else ""
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

