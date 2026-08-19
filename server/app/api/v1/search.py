import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_redis_dep
from app.config import get_settings
from app.core.security import hash_ip
from app.db.session import get_db
from app.matchmaking import queue as queue_repo
from app.matchmaking import session_tracker
from app.matchmaking.topics import (
    excludes_age_filter,
    requires_age_verification,
    validate_topic_selection,
)
from app.models.search_session import SearchSession, SearchSessionStatus
from app.models.user import User
from app.moderation.rate_limiter import RateLimitExceeded, check_rate_limit
from app.schemas.search import SearchStartRequest, SearchStatusResponse, SearchStatusValue

router = APIRouter(tags=["search"])
settings = get_settings()


@router.post("/search/start", response_model=SearchStatusResponse, status_code=status.HTTP_201_CREATED)
async def start_search(
    body: SearchStartRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_dep),
) -> SearchStatusResponse:
    """Начать поиск. Rate limit обязателен для публичных точек нагрузки (см. CLAUDE.md п.7)."""
    client_ip = request.client.host if request.client else "unknown"
    rate_key = hash_ip(client_ip) or "unknown"
    try:
        await check_rate_limit(
            redis,
            bucket="search_start",
            key=rate_key,
            limit=settings.search_start_rate_limit,
            window_seconds=settings.search_start_rate_window_seconds,
        )
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many search attempts, slow down",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    # Тема сама по себе — просто строка от клиента, ей нельзя доверять для
    # чувствительных тем ("Флирт 18+"): сверяемся с уже проверенным флагом
    # на пользователе, а не с тем, что явно/неявно прислал сам клиент
    # (см. код-ревью: age-gate bypass — раньше это никак не проверялось).
    if requires_age_verification(body.topic) and not user.is_age_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="this topic requires age verification — confirm via PUT /settings first",
        )

    # task190826: "Флирт"/"Ролка" — только противоположный пол; "Ролка" —
    # обязателен критерий "ищу/предлагаю сюжет" (см. matchmaking/topics.py).
    # Тема от клиента не более доверенная, чем для age-gate выше — то же самое
    # предупреждение из код-ревью применимо и здесь: проверяем на сервере,
    # а не полагаемся на то, что UI не даст выбрать некорректную комбинацию.
    validation_error = validate_topic_selection(
        body.topic,
        own_gender=user.gender,
        partner_gender=body.partner_gender,
        plot_role=body.plot_role,
    )
    if validation_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=validation_error
        )

    if await queue_repo.is_queued(redis, user.id):
        position = await queue_repo.get_position(redis, user.id)
        return SearchStatusResponse(status=SearchStatusValue.SEARCHING, queue_position=position)

    # task190826: "Ролка" — вкладка без возраста, игнорируем присланные
    # границы вместо того, чтобы полагаться на клиента, что он их не пришлёт.
    age_excluded = excludes_age_filter(body.topic)
    partner_age_min = None if age_excluded else body.partner_age_min
    partner_age_max = None if age_excluded else body.partner_age_max
    partner_age_ranges = [] if age_excluded else body.partner_age_ranges

    entry = queue_repo.QueueEntry(
        user_id=str(user.id),
        topic=body.topic or "",
        gender=user.gender.value,
        age=str(user.age) if user.age is not None else "",
        partner_gender=body.partner_gender.value,
        partner_age_min=str(partner_age_min) if partner_age_min is not None else "",
        partner_age_max=str(partner_age_max) if partner_age_max is not None else "",
        partner_age_ranges=(
            json.dumps([[r.min, r.max] for r in partner_age_ranges])
            if partner_age_ranges
            else ""
        ),
        plot_role=body.plot_role.value if body.plot_role else "",
        joined_at=queue_repo.now_ts(),
    )
    await queue_repo.enqueue(redis, entry)

    db.add(
        SearchSession(
            user_id=user.id,
            topic=body.topic,
            filters_snapshot=body.model_dump(mode="json"),
            status=SearchSessionStatus.SEARCHING,
        )
    )
    await db.commit()

    position = await queue_repo.get_position(redis, user.id)
    return SearchStatusResponse(status=SearchStatusValue.SEARCHING, queue_position=position)


@router.post("/search/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_search(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_dep),
) -> None:
    await queue_repo.dequeue(redis, user.id)
    await session_tracker.mark_cancelled(db, user.id)


@router.get("/search/status", response_model=SearchStatusResponse)
async def search_status(
    user: User = Depends(get_current_user), redis: Redis = Depends(get_redis_dep)
) -> SearchStatusResponse:
    if await queue_repo.is_queued(redis, user.id):
        position = await queue_repo.get_position(redis, user.id)
        return SearchStatusResponse(status=SearchStatusValue.SEARCHING, queue_position=position)
    return SearchStatusResponse(status=SearchStatusValue.IDLE)
