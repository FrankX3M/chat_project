"""Алгоритм подбора пары.

find_match() — чистая функция над состоянием очереди в Redis: находит первую
взаимно совместимую пару (FIFO-приоритет для самого старого ожидающего) и
атомарно резервирует обоих (удаляет из очереди), чтобы два параллельных
вызова не забрали одного и того же пользователя дважды.

Оркестрация (создание chat_room в БД, рассылка WS-события `matched`) — уровнем
выше, в ws/event_handlers.py, чтобы matchmaking/ не зависел от ws/ (см. слои
в CLAUDE.md).
"""

import asyncio
from dataclasses import dataclass

from redis.asyncio import Redis

from app.matchmaking import queue as queue_repo
from app.matchmaking.filters import is_mutually_compatible

# Однопроцессный MVP: защищаем цикл подбора от гонок при конкурентных вызовах
# внутри одного event loop. При горизонтальном масштабировании на несколько
# инстансов сервера этот лок нужно заменить на распределённый (Redis Lock).
_match_lock = asyncio.Lock()


@dataclass(frozen=True)
class MatchResult:
    user1_id: str
    user2_id: str
    topic: str | None


async def find_match(redis: Redis, *, scan_limit: int = 200) -> MatchResult | None:
    async with _match_lock:
        candidates = await queue_repo.list_waiting(redis, limit=scan_limit)
        if len(candidates) < 2:
            return None

        # Разворачиваем как-строки-в-Redis в типизированные dict'ы один раз на
        # кандидата, а не при каждом попарном сравнении (раньше b_filters
        # пересчитывался заново на каждой итерации внутреннего цикла).
        filters_by_candidate = [c.as_filter_dict() for c in candidates]

        for i, a in enumerate(candidates):
            a_filters = filters_by_candidate[i]
            for j in range(i + 1, len(candidates)):
                b = candidates[j]
                b_filters = filters_by_candidate[j]
                if is_mutually_compatible(a_filters, b_filters):
                    # Атомарно резервируем пару, убирая обоих из очереди.
                    await queue_repo.dequeue(redis, a.user_id)
                    await queue_repo.dequeue(redis, b.user_id)
                    topic = a_filters["topic"] or b_filters["topic"]
                    return MatchResult(user1_id=a.user_id, user2_id=b.user_id, topic=topic)
        return None
