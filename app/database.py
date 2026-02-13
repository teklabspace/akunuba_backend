from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from app.config import settings
import ssl

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
    "command_timeout": 30,
    "timeout": 30,
}

# Add SSL for Supabase (required for cloud databases)
# asyncpg accepts ssl as True, False, or an SSLContext
# For Supabase, we need SSL enabled
if "supabase" in settings.DATABASE_URL.lower() or "pooler" in settings.DATABASE_URL.lower():
    connect_args["ssl"] = True  # Enable SSL for Supabase

engine = create_async_engine(
    settings.DATABASE_URL,
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

