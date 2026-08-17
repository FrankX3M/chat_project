"""Обновление статуса `SearchSession` по ходу поиска.

Строка создаётся в `api/v1/search.py::start_search` со статусом `SEARCHING`.
Без вызовов отсюда она навсегда остаётся в этом статусе — а модель
документирует себя как "исторический источник для аналитики/отладки", для
чего переходы `MATCHED`/`CANCELLED` обязательны (см. код-ревью).

Живёт в `matchmaking/`, а не в `api/` или `ws/`, чтобы оба вызывающих места —
REST `POST /search/cancel` и WS `join_queue`/матчинг-цикл — могли им
пользоваться одинаково, не создавая зависимость друг от друга.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.search_session import SearchSession, SearchSessionStatus


async def _latest_searching_session(db: AsyncSession, user_id: uuid.UUID) -> SearchSession | None:
    stmt = (
        select(SearchSession)
        .where(
            SearchSession.user_id == user_id,
            SearchSession.status == SearchSessionStatus.SEARCHING,
        )
        .order_by(SearchSession.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def mark_cancelled(db: AsyncSession, user_id: uuid.UUID) -> None:
    session_row = await _latest_searching_session(db, user_id)
    if session_row is None:
        return
    session_row.status = SearchSessionStatus.CANCELLED
    await db.commit()


async def mark_matched(db: AsyncSession, user_id: uuid.UUID, *, room_id: uuid.UUID) -> None:
    session_row = await _latest_searching_session(db, user_id)
    if session_row is None:
        return
    session_row.status = SearchSessionStatus.MATCHED
    session_row.matched_at = utcnow()
    session_row.room_id = room_id
    await db.commit()
