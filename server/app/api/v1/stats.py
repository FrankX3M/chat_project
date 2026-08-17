from fastapi import APIRouter

from app.schemas.stats import OnlineStatsResponse
from app.ws.connection_manager import connection_manager

router = APIRouter(tags=["stats"])


@router.get("/stats/online", response_model=OnlineStatsResponse)
async def online_stats() -> OnlineStatsResponse:
    """Публичный счётчик — сколько сокетов сейчас подключено к этому инстансу.

    MVP: один процесс, поэтому online_count() — точное число. При переходе на
    несколько инстансов сервера считать через Redis (см. project-structure.md,
    раздел 7 — тот же механизм, что и для connection_manager при масштабировании).
    """
    return OnlineStatsResponse(online=connection_manager.online_count())
