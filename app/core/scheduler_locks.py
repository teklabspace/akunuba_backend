"""
Redis-based distributed lock for scheduled jobs.
Ensures only one instance runs each job when multiple servers are deployed.
"""
import asyncio
from typing import Optional
from app.config import settings
from app.utils.logger import logger

_redis_client = None
_LOCK_PREFIX = "scheduler:lock:"
_LOCK_TTL_SECONDS = 3600  # 1 hour max hold


def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning(f"Redis not available for job locks: {e}")
    return _redis_client


async def try_acquire_job_lock(job_id: str) -> bool:
    """Try to acquire a distributed lock for this job. Returns True if we got the lock."""
    r = _get_redis()
    if not r:
        return True  # No Redis: allow job to run (single-instance behavior)
    key = f"{_LOCK_PREFIX}{job_id}"
    try:
        # SET key 1 NX EX ttl
        acquired = r.set(key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
        return bool(acquired)
    except Exception as e:
        logger.warning(f"Redis lock acquire failed for {job_id}: {e}")
        return True  # On Redis error, allow job to run to avoid silent skip


def release_job_lock(job_id: str) -> None:
    """Release the distributed lock after job completes."""
    r = _get_redis()
    if not r:
        return
    key = f"{_LOCK_PREFIX}{job_id}"
    try:
        r.delete(key)
    except Exception as e:
        logger.warning(f"Redis lock release failed for {job_id}: {e}")


def with_lock(job_id: str, coro_func):
    """Return an async function that runs coro_func only after acquiring the distributed lock."""
    async def wrapper(*args, **kwargs):
        if not await try_acquire_job_lock(job_id):
            logger.info(f"Skipping job {job_id}: lock held by another instance")
            return
        try:
            return await coro_func(*args, **kwargs)
        finally:
            release_job_lock(job_id)
    return wrapper
