from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import time
from app.config import settings
from app.api.v1 import (
    auth_new as auth,
    users,
    accounts,
    assets,
    portfolio,
    trading,
    marketplace,
    payments,
    subscriptions,
    banking,
    documents,
    support,
    notifications,
    reports,
    kyc,
    kyb,
    chat,
    analytics,
    admin,
    files,
    investment,
    concierge,
    crm,
    entities,
    compliance,
    referrals,
    market,
    tasks,
    reminders,
    chat_conversations,
    websocket_chat,
    webhooks,
    advisor,
)
from app.utils.logger import logger
from app.core.responses import (
    success_envelope,
    error_envelope,
    error_code_for,
    flatten_validation_errors,
)
import json
from starlette.responses import Response

# Sentry (optional - set SENTRY_DSN for production)
if getattr(settings, "SENTRY_DSN", None) and settings.SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=getattr(settings, "SENTRY_ENVIRONMENT", None) or settings.APP_ENV,
        traces_sample_rate=getattr(settings, "SENTRY_TRACES_SAMPLE_RATE", 0.1),
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
    )


class NormalizePathMiddleware(BaseHTTPMiddleware):
    """Middleware to normalize double slashes in URL paths"""
    async def dispatch(self, request: Request, call_next):
        # Normalize double slashes in the path by modifying the scope directly
        if "//" in request.scope.get("path", ""):
            normalized_path = request.scope["path"].replace("//", "/")
            request.scope["path"] = normalized_path
            request.scope["raw_path"] = normalized_path.encode("latin-1")
            # Also update path_info if it exists
            if "path_info" in request.scope:
                request.scope["path_info"] = normalized_path
        return await call_next(request)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.APP_DEBUG,
)

# Rate limiting (slowapi) - 60/min default; auth routes use 5/min
from app.core.rate_limit import limiter  # imported unconditionally so @limiter.exempt works
if getattr(settings, "RATE_LIMIT_ENABLED", True):
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    # SlowAPIMiddleware enforces the default 60/min on all otherwise-undecorated
    # routes. Without it, only the explicitly @limiter.limit-decorated auth routes
    # are throttled. Webhooks and health checks are exempted below.
    app.add_middleware(SlowAPIMiddleware)


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Record request duration for /health metrics."""
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        try:
            from app.core.metrics import record_request_time
            record_request_time(duration)
        except Exception:
            pass
        return response


# Paths that must NOT be wrapped in the response envelope: API docs, the OpenAPI
# spec (Swagger reads it raw), health checks, and the root probe.
ENVELOPE_EXCLUDED_PATHS = {"/openapi.json", "/health", "/"}
ENVELOPE_EXCLUDED_PREFIXES = ("/docs", "/redoc")


class ResponseEnvelopeMiddleware(BaseHTTPMiddleware):
    """Wrap every successful JSON response in the standard envelope.

    Produces ``{"success": true, "status_code", "message", "data"}`` uniformly so
    the frontend uses a single parser. Error responses (>=400) are already
    enveloped by the exception handlers and are passed through untouched, as are
    non-JSON responses (file/stream downloads), the docs/spec endpoints, and any
    payload an endpoint already enveloped itself.
    """

    def _rebuild(self, original, content: dict, status_code: int) -> JSONResponse:
        # Drop content-length/content-type: JSONResponse recomputes them. Keep the
        # rest (e.g. anything set by the route) so nothing is silently lost.
        headers = {
            k: v for k, v in original.headers.items()
            if k.lower() not in ("content-length", "content-type")
        }
        return JSONResponse(
            content=content,
            status_code=status_code,
            headers=headers,
            background=original.background,
        )

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        path = request.url.path
        if path in ENVELOPE_EXCLUDED_PATHS or path.startswith(ENVELOPE_EXCLUDED_PREFIXES):
            return response

        # Errors are already enveloped by the exception handlers.
        if response.status_code >= 400:
            return response

        # File/attachment downloads pass through untouched, even when their
        # media type is JSON (e.g. an exported JSON report).
        if "attachment" in response.headers.get("content-disposition", "").lower():
            return response

        content_type = response.headers.get("content-type", "")

        # Normalize an empty-body success (e.g. 204 No Content) into an enveloped 200
        # so the client never receives a bodyless response.
        if response.status_code == 204:
            return self._rebuild(
                response,
                success_envelope(data=None, message="Request successful.", status_code=200),
                status_code=200,
            )

        # Only JSON bodies get wrapped; file/stream/redirect responses pass through.
        if "application/json" not in content_type:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        if not body:
            return self._rebuild(
                response,
                success_envelope(data=None, message="Request successful.", status_code=response.status_code),
                status_code=response.status_code,
            )

        try:
            parsed = json.loads(body)
        except Exception:
            # Body isn't parseable JSON despite the header; return it verbatim
            # (the iterator is already consumed, so reconstruct from the bytes).
            headers = {
                k: v for k, v in response.headers.items() if k.lower() != "content-length"
            }
            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type=content_type,
                background=response.background,
            )

        # Don't double-wrap a payload an endpoint already enveloped.
        if isinstance(parsed, dict) and "success" in parsed and ("data" in parsed or "error" in parsed):
            return self._rebuild(response, parsed, status_code=response.status_code)

        return self._rebuild(
            response,
            success_envelope(data=parsed, message="Request successful.", status_code=response.status_code),
            status_code=response.status_code,
        )


# Add path normalization middleware first (before CORS)
app.add_middleware(NormalizePathMiddleware)
app.add_middleware(RequestTimingMiddleware)
# Wrap successful JSON responses in the standard envelope. Added before CORS so the
# CORS middleware stays outermost and still applies its headers to wrapped responses.
app.add_middleware(ResponseEnvelopeMiddleware)

# CORS configuration - must be added before other middleware
# Allows requests from frontend origins and includes proper CORS headers
# Key points:
# - Allow requests from http://localhost:3000 (or your frontend origin)
# - Include Access-Control-Allow-Origin header
# - Allow Authorization header in CORS requests
if settings.APP_ENV == "development":
    origins = [
        "http://localhost:3000", 
        "http://localhost:5173", 
        "http://127.0.0.1:3000", 
        "http://127.0.0.1:5173",
        "http://localhost:3001",
        "http://127.0.0.1:3001"
    ]
else:
    # In production, parse CORS_ORIGINS (can be string or list)
    if isinstance(settings.CORS_ORIGINS, str):
        # Handle comma-separated string
        origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
    elif isinstance(settings.CORS_ORIGINS, list):
        origins = settings.CORS_ORIGINS
    else:
        origins = [settings.CORS_ORIGINS] if settings.CORS_ORIGINS else []
    
    # Note: localhost origins are intentionally NOT added in production.
    # Combined with allow_credentials=True they are a needless CORS surface;
    # the development branch above already allows localhost for local work.

    # Add production frontend origins
    production_origins = [
        "https://akunuba.vercel.app",
        "https://akunuba.io",
        "https://www.akunuba.io"
    ]
    # Add production origins if not already present
    for prod_origin in production_origins:
        if prod_origin not in origins:
            origins.append(prod_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # List of allowed origins
    allow_origin_regex=None,  # Can use regex patterns if needed
    allow_credentials=True,  # Required for cookies/auth headers
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",      # Explicitly allow Authorization header
        "Content-Type",       # Allow Content-Type header
        "Accept",             # Allow Accept header
        "X-Requested-With",   # Allow X-Requested-With header
        "*"                   # Allow all other headers
    ],
    expose_headers=["*"],     # Expose all response headers to frontend
    max_age=3600,            # Cache preflight requests for 1 hour
)

# Server-side KYC enforcement: the dashboard/data APIs below carry this dependency
# so investors and advisors must have an APPROVED KYC to use them (admins are
# exempt inside the dependency). Onboarding/auth/profile/billing/notification
# routers are intentionally left OPEN so a user can reach and complete KYC:
#   open -> auth, users, accounts, kyc, kyb, subscriptions, notifications, market, admin, webhooks
from fastapi import Depends as _Depends
from app.api.deps import require_kyc_verified
_KYC_GATED = [_Depends(require_kyc_verified)]

# --- Open (onboarding / auth / profile / billing) ---
app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth", tags=["Authentication"])
app.include_router(users.router, prefix=f"{settings.API_V1_PREFIX}/users", tags=["Users"])
app.include_router(accounts.router, prefix=f"{settings.API_V1_PREFIX}/accounts", tags=["Accounts"])
app.include_router(kyc.router, prefix=f"{settings.API_V1_PREFIX}/kyc", tags=["KYC"])
app.include_router(kyb.router, prefix=f"{settings.API_V1_PREFIX}/kyb", tags=["KYB"])
app.include_router(subscriptions.router, prefix=f"{settings.API_V1_PREFIX}/subscriptions", tags=["Subscriptions"])
app.include_router(notifications.router, prefix=f"{settings.API_V1_PREFIX}/notifications", tags=["Notifications"])

# --- KYC-gated (dashboard / data) ---
app.include_router(assets.router, prefix=f"{settings.API_V1_PREFIX}/assets", tags=["Assets"], dependencies=_KYC_GATED)
app.include_router(portfolio.router, prefix=f"{settings.API_V1_PREFIX}/portfolio", tags=["Portfolio"], dependencies=_KYC_GATED)
app.include_router(trading.router, prefix=f"{settings.API_V1_PREFIX}/trading", tags=["Trading"], dependencies=_KYC_GATED)
app.include_router(marketplace.router, prefix=f"{settings.API_V1_PREFIX}/marketplace", tags=["Marketplace"], dependencies=_KYC_GATED)
app.include_router(payments.router, prefix=f"{settings.API_V1_PREFIX}/payments", tags=["Payments"], dependencies=_KYC_GATED)
app.include_router(banking.router, prefix=f"{settings.API_V1_PREFIX}/banking", tags=["Banking"], dependencies=_KYC_GATED)
app.include_router(documents.router, prefix=f"{settings.API_V1_PREFIX}/documents", tags=["Documents"], dependencies=_KYC_GATED)
app.include_router(files.router, prefix=f"{settings.API_V1_PREFIX}/files", tags=["Files"], dependencies=_KYC_GATED)
app.include_router(support.router, prefix=f"{settings.API_V1_PREFIX}/support", tags=["Support"], dependencies=_KYC_GATED)
app.include_router(reports.router, prefix=f"{settings.API_V1_PREFIX}/reports", tags=["Reports"], dependencies=_KYC_GATED)
app.include_router(chat.router, prefix=f"{settings.API_V1_PREFIX}/chat", tags=["Chat"], dependencies=_KYC_GATED)
app.include_router(chat_conversations.router, prefix=f"{settings.API_V1_PREFIX}/chat", tags=["Chat"], dependencies=_KYC_GATED)
# WebSocket route (registered directly on app, not via router)
from app.api.v1.websocket_chat import websocket_chat_endpoint
app.websocket("/ws/chat")(websocket_chat_endpoint)
from app.api.v1.ws_notifications import websocket_notifications_endpoint
app.websocket(f"{settings.API_V1_PREFIX}/ws/notifications")(websocket_notifications_endpoint)
app.include_router(analytics.router, prefix=f"{settings.API_V1_PREFIX}/analytics", tags=["Analytics"], dependencies=_KYC_GATED)
app.include_router(admin.router, prefix=f"{settings.API_V1_PREFIX}/admin", tags=["Admin"])
app.include_router(investment.router, prefix=f"{settings.API_V1_PREFIX}/investment", tags=["Investment"], dependencies=_KYC_GATED)
app.include_router(market.router, prefix=f"{settings.API_V1_PREFIX}/market", tags=["Market"])
app.include_router(tasks.router, prefix=f"{settings.API_V1_PREFIX}/tasks", tags=["Tasks"], dependencies=_KYC_GATED)
app.include_router(reminders.router, prefix=f"{settings.API_V1_PREFIX}/reminders", tags=["Reminders"], dependencies=_KYC_GATED)
app.include_router(concierge.router, prefix=f"{settings.API_V1_PREFIX}/concierge", tags=["Concierge"], dependencies=_KYC_GATED)
app.include_router(crm.router, prefix=f"{settings.API_V1_PREFIX}/crm", tags=["CRM"], dependencies=_KYC_GATED)
app.include_router(entities.router, prefix=f"{settings.API_V1_PREFIX}/entities", tags=["Entities"], dependencies=_KYC_GATED)
app.include_router(compliance.router, prefix=f"{settings.API_V1_PREFIX}/compliance", tags=["Compliance"], dependencies=_KYC_GATED)
app.include_router(referrals.router, prefix=f"{settings.API_V1_PREFIX}/referrals", tags=["Referrals"], dependencies=_KYC_GATED)
app.include_router(advisor.router, prefix=f"{settings.API_V1_PREFIX}/advisor", tags=["Advisor"], dependencies=_KYC_GATED)
app.include_router(webhooks.router, prefix=f"{settings.API_V1_PREFIX}/webhooks", tags=["Webhooks"])


# Helper function to check if origin is allowed
def is_origin_allowed(origin: str) -> bool:
    """Check if the origin is in the allowed list"""
    if not origin:
        return False
    # Normalize origin (remove trailing slash)
    origin = origin.rstrip("/")
    for allowed_origin in origins:
        if allowed_origin.rstrip("/") == origin:
            return True
    return False


# Global exception handlers to ensure proper error responses
# CORS middleware should handle headers automatically, but we ensure responses are properly formatted
def _apply_cors_headers(request: Request, response: JSONResponse, allow_dev_fallback: bool = False) -> JSONResponse:
    """Mirror the CORS headers onto an error response.

    The CORS middleware normally adds these, but it does not always run for
    responses produced by exception handlers, so we ensure they are present.
    """
    origin = request.headers.get("origin")
    if origin and (is_origin_allowed(origin) or (allow_dev_fallback and settings.APP_ENV == "development")):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    elif origin and allow_dev_fallback:
        response.headers["Access-Control-Allow-Origin"] = origins[0] if origins else "*"
    elif not origin:
        if allow_dev_fallback and settings.APP_ENV != "development":
            response.headers["Access-Control-Allow-Origin"] = origins[0] if origins else "*"
        else:
            response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, X-Requested-With, *"
    return response


def _http_exception_to_envelope(exc: HTTPException) -> JSONResponse:
    # FullegoException subclasses carry a stable ``code``; raw HTTPExceptions fall
    # back to a status-derived code. ``detail`` is the user-facing message when it
    # is a plain string.
    code = getattr(exc, "code", None) or error_code_for(exc.status_code)
    message = exc.detail if isinstance(exc.detail, str) else None
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(exc.status_code, message=message, code=code),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return _apply_cors_headers(request, _http_exception_to_envelope(exc))


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
    return _apply_cors_headers(request, _http_exception_to_envelope(exc))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    response = JSONResponse(
        status_code=422,
        content=error_envelope(
            422,
            message="Some of the information provided is invalid. Please check the highlighted fields.",
            code="VALIDATION_ERROR",
            details=flatten_validation_errors(exc.errors()),
        ),
    )
    return _apply_cors_headers(request, response)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    # Never leak internals to clients; show the real error only in debug.
    message = str(exc) if settings.APP_DEBUG else "Something went wrong on our end. Please try again."
    response = JSONResponse(
        status_code=500,
        content=error_envelope(500, message=message, code="INTERNAL_ERROR"),
    )
    response = _apply_cors_headers(request, response, allow_dev_fallback=True)
    response.headers["Access-Control-Expose-Headers"] = "*"
    return response


@app.options("/{full_path:path}")
@limiter.exempt
async def options_handler(full_path: str, request: Request):
    """Handle CORS preflight requests (OPTIONS method)
    
    This endpoint handles CORS preflight requests from browsers.
    It explicitly allows:
    - Authorization header (for Bearer token authentication)
    - Content-Type header (for JSON/form-data requests)
    - All other standard headers
    """
    origin = request.headers.get("origin")
    response = JSONResponse(content={})
    
    # Check if origin is allowed
    if origin:
        # Normalize origin (remove trailing slash)
        normalized_origin = origin.rstrip("/")
        # Check if origin is in allowed list
        origin_allowed = False
        for allowed_origin in origins:
            if allowed_origin.rstrip("/") == normalized_origin:
                origin_allowed = True
                break
        
        if origin_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, X-Requested-With, *"
            response.headers["Access-Control-Max-Age"] = "3600"
            response.headers["Access-Control-Expose-Headers"] = "*"
    else:
        # No origin header, allow in development
        if settings.APP_ENV == "development":
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, X-Requested-With, *"
    
    return response


@app.get("/")
@limiter.exempt
async def root():
    return {
        "message": "Fullego Backend API",
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
@limiter.exempt
async def health_check():
    """Production health: status, version, DB/Redis checks, and metrics."""
    from app.core.metrics import get_metrics
    payload = {
        "status": "healthy",
        "version": settings.APP_VERSION,
    }
    # Optional: DB check
    try:
        from app.database import engine
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        payload["database"] = "ok"
    except Exception as e:
        payload["database"] = "error"
        payload["status"] = "degraded"
    # Optional: Redis check
    try:
        import redis
        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        payload["redis"] = "ok"
    except Exception:
        payload["redis"] = "unavailable"
    payload["metrics"] = get_metrics()
    return payload


@app.on_event("startup")
async def startup_event():
    try:
        logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
        
        # Initialize Redis for WebSocket pub/sub
        from app.core.websocket_manager import manager
        await manager.connect_redis()
        
        # Check 2FA libraries availability
        try:
            import pyotp
            import qrcode
            logger.info("[OK] 2FA libraries (pyotp, qrcode) are available")
        except ImportError as e:
            logger.warning(f"[WARN] 2FA libraries not available: {e}")
            logger.warning("   Install with: pip install pyotp qrcode[pil]")
            logger.warning("   Or: python -m pip install pyotp qrcode[pil]")
        
        # Test database connection with timeout (non-blocking)
        # Run in background so it doesn't block startup
        async def test_db_connection():
            try:
                import asyncio
                from app.database import engine
                from sqlalchemy import text
                logger.info("Testing database connection...")
                async with engine.connect() as conn:
                    # Add timeout to prevent hanging - increased for cloud connections
                    await asyncio.wait_for(
                        conn.execute(text("SELECT 1")),
                        timeout=30.0  # 30 seconds timeout
                    )
                logger.info("[OK] Database connection verified successfully")
            except asyncio.TimeoutError:
                logger.warning("[WARN] Database connection test timed out after 30 seconds")
                logger.warning("   The connection might work for actual requests.")
                logger.warning("   If login fails, check:")
                logger.warning("   1. DATABASE_URL is correct (host, port, credentials)")
                logger.warning("   2. Supabase network restrictions allow all IPs")
                logger.warning("   3. Try Transaction Pooler (port 6543) instead of Session (5432)")
            except Exception as e:
                logger.warning(f"[WARN] Database connection test failed: {type(e).__name__}: {e}")
                logger.warning("   The connection might still work for actual requests.")
        
        # Run test in background (don't await - non-blocking)
        import asyncio
        asyncio.create_task(test_db_connection())
        
        # Start background job scheduler
        from app.core.scheduler import scheduler, setup_scheduled_tasks
        if settings.APP_ENV != "test":
            try:
                setup_scheduled_tasks()
                scheduler.start()
                logger.info("Background job scheduler started")
            except Exception as e:
                logger.error(f"Failed to start scheduler: {e}")
                # Don't fail startup if scheduler fails
    except Exception as e:
        logger.error(f"Startup event failed: {e}", exc_info=True)
        raise  # Re-raise to prevent silent failures


@app.on_event("shutdown")
async def shutdown_event():
    try:
        from app.integrations.posthog_client import PosthogClient
        from app.core.scheduler import scheduler
        from app.core.websocket_manager import manager
        
        try:
            scheduler.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down scheduler: {e}")
        
        try:
            PosthogClient.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down PostHog: {e}")
        
        try:
            await manager.disconnect_redis()
        except Exception as e:
            logger.error(f"Error disconnecting Redis: {e}")
        
        logger.info("Shutting down application")
    except Exception as e:
        logger.error(f"Shutdown event failed: {e}", exc_info=True)

