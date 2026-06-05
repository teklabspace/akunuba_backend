import httpx

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
    _IMPORT_ERROR = None
except ImportError as exc:
    SUPABASE_AVAILABLE = False
    create_client = None
    Client = None
    _IMPORT_ERROR = exc

from typing import Optional
from app.config import settings
from app.utils.logger import logger


class SupabaseClient:
    _instance: Optional["Client"] = None

    @classmethod
    def _storage_base_url(cls) -> str:
        return f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1"

    @classmethod
    def _auth_headers(cls, content_type: Optional[str] = None, upsert: bool = False) -> dict:
        headers = {
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        }
        if content_type:
            headers["Content-Type"] = content_type
        if upsert:
            headers["x-upsert"] = "true"
        return headers

    @classmethod
    def _ensure_configured(cls) -> None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured")

    @classmethod
    def get_client(cls) -> Optional["Client"]:
        if not SUPABASE_AVAILABLE:
            if _IMPORT_ERROR:
                logger.warning(
                    "Supabase SDK import failed (%s). Using HTTP storage fallback.",
                    _IMPORT_ERROR,
                )
            else:
                logger.warning("Supabase SDK not installed. Using HTTP storage fallback.")
            return None
        if cls._instance is None:
            cls._ensure_configured()
            cls._instance = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_ROLE_KEY,
            )
            logger.info("Supabase client initialized")
        return cls._instance

    @classmethod
    def _upload_via_http(
        cls,
        bucket: str,
        file_path: str,
        file_data: bytes,
        content_type: str,
        upsert: bool = True,
    ) -> str:
        cls._ensure_configured()
        url = f"{cls._storage_base_url()}/object/{bucket}/{file_path}"
        headers = cls._auth_headers(content_type=content_type, upsert=upsert)
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, content=file_data, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Supabase storage upload failed ({response.status_code}): {response.text[:500]}"
                )
        return file_path

    @classmethod
    def _get_public_url_via_http(cls, bucket: str, file_path: str) -> str:
        cls._ensure_configured()
        return (
            f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/public/"
            f"{bucket}/{file_path}"
        )

    @classmethod
    def _delete_via_http(cls, bucket: str, file_path: str) -> bool:
        cls._ensure_configured()
        url = f"{cls._storage_base_url()}/object/{bucket}/{file_path}"
        headers = cls._auth_headers()
        with httpx.Client(timeout=30.0) as client:
            response = client.delete(url, headers=headers)
            if response.status_code >= 400:
                logger.error(
                    "Supabase storage delete failed (%s): %s",
                    response.status_code,
                    response.text[:500],
                )
                return False
        return True

    @classmethod
    def _download_via_http(cls, bucket: str, file_path: str) -> bytes:
        cls._ensure_configured()
        url = f"{cls._storage_base_url()}/object/{bucket}/{file_path}"
        headers = cls._auth_headers()
        with httpx.Client(timeout=60.0) as client:
            response = client.get(url, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Supabase storage download failed ({response.status_code}): {response.text[:500]}"
                )
            return response.content

    @classmethod
    def upload_file(
        cls,
        bucket: str,
        file_path: str,
        file_data: bytes,
        content_type: str = "application/octet-stream",
        upsert: bool = True,
    ) -> str:
        client = cls.get_client()
        if client is None:
            return cls._upload_via_http(bucket, file_path, file_data, content_type, upsert=upsert)

        file_options = {"content-type": content_type}
        try:
            try:
                response = client.storage.from_(bucket).upload(
                    file_path,
                    file_data,
                    file_options=file_options,
                )
            except Exception as upload_error:
                if upsert and (
                    "already exists" in str(upload_error).lower()
                    or "duplicate" in str(upload_error).lower()
                ):
                    logger.warning("File exists, attempting to overwrite: %s", file_path)
                    cls.delete_file(bucket, file_path)
                    response = client.storage.from_(bucket).upload(
                        file_path,
                        file_data,
                        file_options=file_options,
                    )
                else:
                    raise
            if isinstance(response, dict):
                return response.get("path", file_path)
            return file_path
        except Exception as e:
            error_str = str(e)
            if "already exists" in error_str.lower() or "duplicate" in error_str.lower():
                try:
                    cls.delete_file(bucket, file_path)
                    response = client.storage.from_(bucket).upload(
                        file_path,
                        file_data,
                        file_options=file_options,
                    )
                    if isinstance(response, dict):
                        return response.get("path", file_path)
                    return file_path
                except Exception as delete_error:
                    logger.error("Failed to overwrite existing file: %s", delete_error)
                    raise
            if "Header value must be str or bytes" in error_str or "not <class 'bool'>" in error_str:
                try:
                    response = client.storage.from_(bucket).upload(file_path, file_data)
                    if isinstance(response, dict):
                        return response.get("path", file_path)
                    return file_path
                except Exception as fallback_error:
                    logger.warning("SDK upload failed, trying HTTP fallback: %s", fallback_error)
                    return cls._upload_via_http(
                        bucket, file_path, file_data, content_type, upsert=upsert
                    )
            logger.warning("SDK upload failed, trying HTTP fallback: %s", e)
            return cls._upload_via_http(bucket, file_path, file_data, content_type, upsert=upsert)

    @classmethod
    def get_file_url(cls, bucket: str, file_path: str) -> str:
        client = cls.get_client()
        if client is None:
            return cls._get_public_url_via_http(bucket, file_path)

        try:
            response = client.storage.from_(bucket).get_public_url(file_path)
            if isinstance(response, dict):
                public_url = response.get("publicUrl", "")
            else:
                public_url = str(response) if response else ""

            if public_url and not public_url.startswith(("http://", "https://")):
                if public_url.startswith("/"):
                    public_url = f"{settings.SUPABASE_URL}{public_url}"
                else:
                    public_url = (
                        f"{settings.SUPABASE_URL}/storage/v1/object/public/{bucket}/{file_path}"
                    )

            if public_url and public_url.endswith("?"):
                public_url = public_url.rstrip("?")

            return public_url or cls._get_public_url_via_http(bucket, file_path)
        except Exception as e:
            logger.warning("SDK get_file_url failed, using HTTP URL: %s", e)
            return cls._get_public_url_via_http(bucket, file_path)

    @classmethod
    def delete_file(cls, bucket: str, file_path: str) -> bool:
        client = cls.get_client()
        if client is None:
            return cls._delete_via_http(bucket, file_path)

        try:
            response = client.storage.from_(bucket).remove([file_path])
            if isinstance(response, list) and len(response) > 0:
                return True
            return True
        except Exception as e:
            logger.error("Failed to delete file from Supabase Storage: %s", e)
            return cls._delete_via_http(bucket, file_path)

    @classmethod
    def download_file(cls, bucket: str, file_path: str) -> bytes:
        client = cls.get_client()
        if client is None:
            return cls._download_via_http(bucket, file_path)

        try:
            response = client.storage.from_(bucket).download(file_path)
            if isinstance(response, bytes):
                return response
            if isinstance(response, dict):
                return response.get("data", b"")
            return b""
        except Exception as e:
            logger.warning("SDK download failed, trying HTTP fallback: %s", e)
            return cls._download_via_http(bucket, file_path)

    @classmethod
    def list_files(cls, bucket: str, folder: str = "") -> list:
        client = cls.get_client()
        if client is None:
            cls._ensure_configured()
            url = f"{cls._storage_base_url()}/object/list/{bucket}"
            headers = cls._auth_headers(content_type="application/json")
            payload = {"prefix": folder, "limit": 100, "offset": 0}
            with httpx.Client(timeout=30.0) as http_client:
                response = http_client.post(url, json=payload, headers=headers)
                if response.status_code >= 400:
                    logger.error("Supabase list files failed: %s", response.text[:500])
                    return []
                data = response.json()
                return data if isinstance(data, list) else []

        try:
            response = client.storage.from_(bucket).list(folder)
            if isinstance(response, list):
                return response
            return []
        except Exception as e:
            logger.error("Failed to list files from Supabase Storage: %s", e)
            return []
