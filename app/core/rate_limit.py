"""
API rate limiting using slowapi with Redis storage.
- Login/auth endpoints: 5 requests/minute per IP
- General API: 60 requests/minute per IP
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request
from app.config import settings

# Use Redis for distributed rate limiting across instances
_storage_uri = settings.REDIS_URL if getattr(settings, "REDIS_URL", None) else "memory://"


def client_ip_key(request: Request) -> str:
    """Rate-limit key based on the real client IP.

    Behind a proxy/load balancer (e.g. Render), the socket peer is the proxy,
    so get_remote_address() would bucket every user together. Prefer the first
    hop in X-Forwarded-For, which the platform sets, and fall back to the peer.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=client_ip_key,
    default_limits=["60/minute"],  # General API: 60/min per client IP
    storage_uri=_storage_uri,
    # Resilience: the limit now applies app-wide via SlowAPIMiddleware, so a Redis
    # outage must not take down the API. Fall back to in-memory counting and, if
    # the backend still errors, allow the request rather than 500-ing.
    in_memory_fallback_enabled=True,
    swallow_errors=True,
)

# Limits for specific routes (decorator or dependency)
LOGIN_RATE_LIMIT = "5/minute"   # login, register, password-reset
AUTH_RATE_LIMIT = "5/minute"   # token refresh, OTP
PUBLIC_API_LIMIT = "60/minute" # public/unauthenticated endpoints
