from functools import lru_cache

from redis.asyncio import Redis, from_url

from app.config import get_settings


@lru_cache
def get_redis() -> Redis:
    """Единый на процесс async Redis-клиент (connection pool внутри)."""
    settings = get_settings()
    return from_url(settings.redis_url, decode_responses=True)
