from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import settings
from app.api.v1 import auth_new as auth, users, accounts, assets, portfolio, trading, marketplace, payments, subscriptions, banking, documents, support, notifications, reports, kyc, kyb, chat, analytics, admin, files, investment, concierge, crm, entities, compliance
from app.utils.logger import logger


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

# Add path normalization middleware first (before CORS)
app.add_middleware(NormalizePathMiddleware)

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
    
    # Always add localhost origins for development/testing even in production
    localhost_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173"
    ]
    # Add localhost origins if not already present
    for localhost_origin in localhost_origins:
        if localhost_origin not in origins:
            origins.append(localhost_origin)
    
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

app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth", tags=["Authentication"])
app.include_router(users.router, prefix=f"{settings.API_V1_PREFIX}/users", tags=["Users"])
app.include_router(accounts.router, prefix=f"{settings.API_V1_PREFIX}/accounts", tags=["Accounts"])
app.include_router(kyc.router, prefix=f"{settings.API_V1_PREFIX}/kyc", tags=["KYC"])
app.include_router(kyb.router, prefix=f"{settings.API_V1_PREFIX}/kyb", tags=["KYB"])
app.include_router(assets.router, prefix=f"{settings.API_V1_PREFIX}/assets", tags=["Assets"])
app.include_router(portfolio.router, prefix=f"{settings.API_V1_PREFIX}/portfolio", tags=["Portfolio"])
app.include_router(trading.router, prefix=f"{settings.API_V1_PREFIX}/trading", tags=["Trading"])
app.include_router(marketplace.router, prefix=f"{settings.API_V1_PREFIX}/marketplace", tags=["Marketplace"])
app.include_router(payments.router, prefix=f"{settings.API_V1_PREFIX}/payments", tags=["Payments"])
app.include_router(subscriptions.router, prefix=f"{settings.API_V1_PREFIX}/subscriptions", tags=["Subscriptions"])
app.include_router(banking.router, prefix=f"{settings.API_V1_PREFIX}/banking", tags=["Banking"])
app.include_router(documents.router, prefix=f"{settings.API_V1_PREFIX}/documents", tags=["Documents"])
app.include_router(files.router, prefix=f"{settings.API_V1_PREFIX}/files", tags=["Files"])
app.include_router(support.router, prefix=f"{settings.API_V1_PREFIX}/support", tags=["Support"])
app.include_router(notifications.router, prefix=f"{settings.API_V1_PREFIX}/notifications", tags=["Notifications"])
app.include_router(reports.router, prefix=f"{settings.API_V1_PREFIX}/reports", tags=["Reports"])
app.include_router(chat.router, prefix=f"{settings.API_V1_PREFIX}/chat", tags=["Chat"])
app.include_router(analytics.router, prefix=f"{settings.API_V1_PREFIX}/analytics", tags=["Analytics"])
app.include_router(admin.router, prefix=f"{settings.API_V1_PREFIX}/admin", tags=["Admin"])
app.include_router(investment.router, prefix=f"{settings.API_V1_PREFIX}/investment", tags=["Investment"])
app.include_router(concierge.router, prefix=f"{settings.API_V1_PREFIX}/concierge", tags=["Concierge"])
app.include_router(crm.router, prefix=f"{settings.API_V1_PREFIX}/crm", tags=["CRM"])
app.include_router(entities.router, prefix=f"{settings.API_V1_PREFIX}/entities", tags=["Entities"])
app.include_router(compliance.router, prefix=f"{settings.API_V1_PREFIX}/compliance", tags=["Compliance"])


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
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    response = JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail if isinstance(exc.detail, str) else exc.detail}
    )
    # Ensure CORS headers are present (CORS middleware should add them, but this ensures it)
    origin = request.headers.get("origin")
    if origin and is_origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, X-Requested-With, *"
    elif not origin:
        # Allow requests without origin (e.g., Postman, curl)
        response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
    response = JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail if isinstance(exc.detail, str) else exc.detail}
    )
    # Ensure CORS headers are present
    origin = request.headers.get("origin")
    if origin and is_origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, X-Requested-With, *"
    elif not origin:
        response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    response = JSONResponse(
        status_code=422,
        content={"detail": exc.errors()}
    )
    # Ensure CORS headers are present
    origin = request.headers.get("origin")
    if origin and is_origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, X-Requested-With, *"
    return response


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    detail = "Internal server error"
    if settings.APP_DEBUG:
        detail = str(exc)
    response = JSONResponse(
        status_code=500,
        content={"detail": detail}
    )
    # Ensure CORS headers are ALWAYS present for 500 errors
    origin = request.headers.get("origin")
    if origin:
        # Check if origin is allowed, if not, still allow it in development
        if is_origin_allowed(origin) or settings.APP_ENV == "development":
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        else:
            # In production, only allow from allowed origins
            response.headers["Access-Control-Allow-Origin"] = origins[0] if origins else "*"
    else:
        # No origin header, allow all in development
        if settings.APP_ENV == "development":
            response.headers["Access-Control-Allow-Origin"] = "*"
        else:
            response.headers["Access-Control-Allow-Origin"] = origins[0] if origins else "*"
    
    # Always add these headers
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Accept, X-Requested-With, *"
    response.headers["Access-Control-Expose-Headers"] = "*"
    return response


@app.options("/{full_path:path}")
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
async def root():
    return {
        "message": "Fullego Backend API",
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": settings.APP_VERSION
    }


@app.on_event("startup")
async def startup_event():
    try:
        logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
        
        # Check 2FA libraries availability
        try:
            import pyotp
            import qrcode
            logger.info("✅ 2FA libraries (pyotp, qrcode) are available")
        except ImportError as e:
            logger.warning(f"⚠️  2FA libraries not available: {e}")
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
                logger.info("✅ Database connection verified successfully")
            except asyncio.TimeoutError:
                logger.warning("⚠️ Database connection test timed out after 30 seconds")
                logger.warning("   The connection might work for actual requests.")
                logger.warning("   If login fails, check:")
                logger.warning("   1. DATABASE_URL is correct (host, port, credentials)")
                logger.warning("   2. Supabase network restrictions allow all IPs")
                logger.warning("   3. Try Transaction Pooler (port 6543) instead of Session (5432)")
            except Exception as e:
                logger.warning(f"⚠️ Database connection test failed: {type(e).__name__}: {e}")
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
        
        try:
            scheduler.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down scheduler: {e}")
        
        try:
            PosthogClient.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down PostHog: {e}")
        
        logger.info("Shutting down application")
    except Exception as e:
        logger.error(f"Shutdown event failed: {e}", exc_info=True)

