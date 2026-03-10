"""
API rate limiting using slowapi with Redis storage.
- Login/auth endpoints: 5 requests/minute per IP
- General API: 60 requests/minute per IP
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings

# Use Redis for distributed rate limiting across instances
_storage_uri = settings.REDIS_URL if getattr(settings, "REDIS_URL", None) else "memory://"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],  # General API: 60/min per IP
    storage_uri=_storage_uri,
)

# Limits for specific routes (decorator or dependency)
LOGIN_RATE_LIMIT = "5/minute"   # login, register, password-reset
AUTH_RATE_LIMIT = "5/minute"   # token refresh, OTP
PUBLIC_API_LIMIT = "60/minute" # public/unauthenticated endpoints
