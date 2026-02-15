from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from app.config import settings
import ssl
from urllib.parse import urlparse, urlunparse, parse_qs
from app.utils.logger import logger

# Clean DATABASE_URL - remove query parameters that asyncpg doesn't understand
# asyncpg doesn't support sslmode in the URL, we handle SSL via connect_args
database_url = settings.DATABASE_URL

# Validate DATABASE_URL is set and not empty
if not database_url or not database_url.strip():
    raise ValueError("DATABASE_URL environment variable is not set or is empty. Please set it in Render dashboard.")

# Validate it starts with the correct scheme
if not database_url.startswith(('postgresql://', 'postgresql+asyncpg://')):
    raise ValueError(f"Invalid DATABASE_URL format. Must start with 'postgresql://' or 'postgresql+asyncpg://'. Got: {database_url[:50]}...")

logger.info(f"Using DATABASE_URL: {database_url.split('@')[1] if '@' in database_url else '***'}")  # Log host only for security

# Remove query parameters manually (more robust)
if '?' in database_url:
    original_url = database_url
    clean_url = database_url.split('?')[0]
    logger.warning(f"Removed query parameters from DATABASE_URL: {original_url} -> {clean_url}")
else:
    clean_url = database_url

# Also parse and reconstruct to be safe
parsed = urlparse(clean_url)
clean_url = urlunparse((
    parsed.scheme,
    parsed.netloc,
    parsed.path,
    parsed.params,
    '',  # Ensure no query string
    parsed.fragment
))

# Configure SSL for Supabase connections
# For asyncpg, SSL should be True or an SSLContext
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Build connect_args for asyncpg
connect_args = {
    "server_settings": {
        "application_name": "fullego_backend"
    },
    "command_timeout": 60,  # Increased timeout for cloud connections
    "timeout": 60,           # Increased connection timeout
}

# Add SSL for Supabase (required for cloud databases)
# asyncpg accepts ssl as True, False, or an SSLContext
# For Supabase, we need SSL enabled
if "supabase" in clean_url.lower() or "pooler" in clean_url.lower():
    # Use SSL context for better compatibility
    connect_args["ssl"] = ssl_context  # Use SSL context instead of True
    logger.info(f"SSL enabled for database connection to: {parsed.netloc}")

engine = create_async_engine(
    clean_url,  # Use cleaned URL without query parameters
    echo=settings.APP_DEBUG,
    pool_pre_ping=True,  # Verify connections before using them
    pool_recycle=3600,   # Recycle connections after 1 hour
    pool_timeout=30,      # Timeout for getting connection from pool (seconds)
    connect_args=connect_args
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

