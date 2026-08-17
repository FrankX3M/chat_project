"""Очередь ожидающих в Redis.

MVP использует один общий sorted set (FIFO по времени входа) вместо
шардирования по теме `queue:{topic}` — при росте нагрузки это первое место
для оптимизации (см. anonymous-chat-structure.md, "Масштабируемость очереди").
Совместимость по теме всё равно проверяется в matchmaking/filters.py, так что
корректность не зависит от структуры хранения.

Состояние очереди — только в Redis, не в PostgreSQL (см. CLAUDE.md п.3).
"""

import time
import uuid
from dataclasses import asdict, dataclass

from redis.asyncio import Redis

QUEUE_KEY = "queue:waiting"
ENTRY_KEY_PREFIX = "queue:entry:"
# Safety-net TTL: если процесс упал между enqueue и dequeue, запись не висит вечно.
ENTRY_TTL_SECONDS = 300


def _entry_key(user_id: uuid.UUID | str) -> str:
    return f"{ENTRY_KEY_PREFIX}{user_id}"


@dataclass
class QueueEntry:
    user_id: str
    topic: str
    gender: str
    age: str  # "" если не указан — Redis hash хранит только строки
    partner_gender: str
    partner_age_min: str
    partner_age_max: str
    joined_at: float

    def to_redis_hash(self) -> dict[str, str]:
        return {k: str(v) for k, v in asdict(self).items()}

    @classmethod
    def from_redis_hash(cls, data: dict[str, str]) -> "QueueEntry":
        return cls(
            user_id=data["user_id"],
            topic=data["topic"],
            gender=data["gender"],
            age=data["age"],
            partner_gender=data["partner_gender"],
            partner_age_min=data["partner_age_min"],
            partner_age_max=data["partner_age_max"],
            joined_at=float(data["joined_at"]),
        )

    def as_filter_dict(self) -> dict:
        """Плоский dict с типизированными значениями для matchmaking/filters.py."""
        return {
            "user_id": self.user_id,
            "topic": self.topic or None,
            "gender": self.gender,
            "age": int(self.age) if self.age else None,
            "partner_gender": self.partner_gender,
            "partner_age_min": int(self.partner_age_min) if self.partner_age_min else None,
            "partner_age_max": int(self.partner_age_max) if self.partner_age_max else None,
        }


async def enqueue(redis: Redis, entry: QueueEntry) -> None:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(_entry_key(entry.user_id), mapping=entry.to_redis_hash())
        pipe.expire(_entry_key(entry.user_id), ENTRY_TTL_SECONDS)
        pipe.zadd(QUEUE_KEY, {entry.user_id: entry.joined_at})
        await pipe.execute()


async def dequeue(redis: Redis, user_id: uuid.UUID | str) -> None:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.zrem(QUEUE_KEY, str(user_id))
        pipe.delete(_entry_key(user_id))
        await pipe.execute()


async def is_queued(redis: Redis, user_id: uuid.UUID | str) -> bool:
    rank = await redis.zrank(QUEUE_KEY, str(user_id))
    return rank is not None


async def get_position(redis: Redis, user_id: uuid.UUID | str) -> int | None:
    rank = await redis.zrank(QUEUE_KEY, str(user_id))
    return None if rank is None else rank + 1


async def list_waiting(redis: Redis, limit: int = 200) -> list[QueueEntry]:
    """Кандидаты в порядке FIFO (старые — первыми)."""
    user_ids = await redis.zrange(QUEUE_KEY, 0, limit - 1)
    if not user_ids:
        return []

    async with redis.pipeline(transaction=False) as pipe:
        for uid in user_ids:
            pipe.hgetall(_entry_key(uid))
        results = await pipe.execute()

    entries: list[QueueEntry] = []
    for uid, data in zip(user_ids, results, strict=True):
        if not data:
            # Запись устарела/удалена — подчистим "осиротевший" id из zset.
            await redis.zrem(QUEUE_KEY, uid)
            continue
        entries.append(QueueEntry.from_redis_hash(data))
    return entries


def now_ts() -> float:
    return time.time()
