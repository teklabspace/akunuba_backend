try:
    from posthog import Posthog
    POSTHOG_AVAILABLE = True
except ImportError:
    POSTHOG_AVAILABLE = False
    Posthog = None

from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any


class PosthogClient:
    _instance: Optional[Posthog] = None

    @classmethod
    def get_client(cls) -> Optional[Posthog]:
        if not POSTHOG_AVAILABLE:
            logger.warning("PostHog SDK not installed. Install with: pip install posthog")
            return None
        if not settings.POSTHOG_PROJECT_API_KEY:
            logger.warning("PostHog Project API key not configured")
            return None
        if cls._instance is None:
            try:
                cls._instance = Posthog(
                    project_api_key=settings.POSTHOG_PROJECT_API_KEY,
                    host=settings.POSTHOG_HOST
                )
                logger.info("PostHog client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize PostHog client: {e}")
                return None
        return cls._instance

    @classmethod
    def identify(cls, distinct_id: str, properties: Dict[str, Any]) -> bool:
        client = cls.get_client()
        if not client:
            return False
        try:
            client.identify(distinct_id=distinct_id, properties=properties)
            return True
        except Exception as e:
            logger.error(f"Failed to identify user in PostHog: {e}")
            return False

    @classmethod
    def track(cls, distinct_id: str, event: str, properties: Optional[Dict[str, Any]] = None) -> bool:
        client = cls.get_client()
        if not client:
            return False
        try:
            client.capture(distinct_id=distinct_id, event=event, properties=properties or {})
            return True
        except Exception as e:
            logger.error(f"Failed to track event in PostHog: {e}")
            return False

    @classmethod
    def shutdown(cls):
        client = cls.get_client()
        if client:
            client.shutdown()

