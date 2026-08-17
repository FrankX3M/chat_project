"""Анти-спам rate limiting для публичных точек входа (см. CLAUDE.md п.7).

MVP: простой fixed-window счётчик в Redis, ключ rate:{bucket}:{key}.
Любой новый публичный POST-эндпоинт без модераторской авторизации по
умолчанию должен быть обёрнут этой проверкой, а не оставаться открытым.
"""

from redis.asyncio import Redis


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"rate limit exceeded, retry after {retry_after}s")


async def check_rate_limit(
    redis: Redis, *, bucket: str, key: str, limit: int, window_seconds: int
) -> None:
    """Бросает RateLimitExceeded, если key превысил limit запросов за window_seconds."""
    redis_key = f"rate:{bucket}:{key}"
    current = await redis.incr(redis_key)
    if current == 1:
        await redis.expire(redis_key, window_seconds)
    if current > limit:
        ttl = await redis.ttl(redis_key)
        raise RateLimitExceeded(retry_after=max(ttl, 1))
