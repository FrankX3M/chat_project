"""Обработка входящих WS-событий + фоновый цикл матчинга.

Здесь единственное место, где matchmaking/, chat/ и ws/connection_manager
связываются вместе — сами модули matchmaking/chat про WS ничего не знают
(см. слои в CLAUDE.md).
"""

import asyncio
import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat import room_manager
from app.chat.message_service import MessageRejected, send_message
from app.config import get_settings
from app.db.session import async_session_maker
from app.matchmaking import queue as queue_repo
from app.matchmaking import session_tracker
from app.matchmaking.matcher import find_match
from app.matchmaking.topics import requires_age_verification
from app.models.chat_room import ChatRoom, EndReason
from app.models.user import User
from app.moderation.rate_limiter import RateLimitExceeded, check_rate_limit
from app.schemas.ws_events import (
    CancelQueueEvent,
    ClientEvent,
    ClientMessageEvent,
    ErrorEvent,
    ErrorPayload,
    JoinQueueEvent,
    LeaveEvent,
    MatchedEvent,
    MatchedPayload,
    PartnerInfo,
    PartnerLeftEvent,
    PartnerLeftPayload,
    QueuePositionEvent,
    QueuePositionPayload,
    ServerMessageEvent,
    ServerMessagePayload,
    ServerTypingEvent,
    ServerTypingPayload,
    TypingEvent,
)
from app.ws.connection_manager import connection_manager

logger = logging.getLogger(__name__)
settings = get_settings()


def parse_client_event(raw: dict) -> ClientEvent:
    """Валидирует входящий JSON против дискриминированного union ClientEvent."""
    from pydantic import TypeAdapter

    adapter = TypeAdapter(ClientEvent)
    return adapter.validate_python(raw)


async def _send_error(user_id: uuid.UUID, code: str, message: str) -> None:
    await connection_manager.send_event(
        user_id, ErrorEvent(payload=ErrorPayload(code=code, message=message))
    )


async def dispatch_event(
    user: User, event: ClientEvent, db: AsyncSession, redis: Redis
) -> None:
    if isinstance(event, JoinQueueEvent):
        await _handle_join_queue(user, event, redis)
    elif isinstance(event, CancelQueueEvent):
        await queue_repo.dequeue(redis, user.id)
        await session_tracker.mark_cancelled(db, user.id)
    elif isinstance(event, ClientMessageEvent):
        await _handle_message(user, event, db, redis)
    elif isinstance(event, TypingEvent):
        await _handle_typing(user, event, db, redis)
    elif isinstance(event, LeaveEvent):
        await _handle_leave(user, event, db, reason=EndReason.USER_LEFT)
    else:  # pragma: no cover - защита от расширения union без обработчика
        await _send_error(user.id, "unsupported_event", "event type not handled")


async def _handle_join_queue(user: User, event: JoinQueueEvent, redis: Redis) -> None:
    payload = event.payload
    # Тот же age-gate, что и в REST api/v1/search.py::start_search — WS это
    # независимая точка входа в ту же очередь, доверять топику от клиента
    # напрямую тут так же нельзя (см. код-ревью: age-gate bypass).
    if requires_age_verification(payload.topic) and not user.is_age_verified:
        await _send_error(
            user.id,
            "age_verification_required",
            "this topic requires age verification — confirm via PUT /settings first",
        )
        return
    if await queue_repo.is_queued(redis, user.id):
        return
    entry = queue_repo.QueueEntry(
        user_id=str(user.id),
        topic=payload.topic or "",
        gender=user.gender.value,
        age=str(user.age) if user.age is not None else "",
        partner_gender=payload.partner_gender.value,
        partner_age_min=str(payload.partner_age_min) if payload.partner_age_min else "",
        partner_age_max=str(payload.partner_age_max) if payload.partner_age_max else "",
        joined_at=queue_repo.now_ts(),
    )
    await queue_repo.enqueue(redis, entry)
    position = await queue_repo.get_position(redis, user.id)
    if position is not None:
        await connection_manager.send_event(
            user.id, QueuePositionEvent(payload=QueuePositionPayload(position=position))
        )


async def _get_room_or_error(db: AsyncSession, user: User, room_id: uuid.UUID) -> ChatRoom | None:
    room = await room_manager.get_room(db, room_id)
    if room is None or not room_manager.is_participant(room, user.id):
        await _send_error(user.id, "room_not_found", "room does not exist or access denied")
        return None
    return room


async def _check_ws_rate_limit(
    redis: Redis, user: User, *, bucket: str, limit: int, window_seconds: int
) -> bool:
    """Тот же fixed-window rate limit, что и на REST /search/start, но для
    WS `message`/`typing` — раньше сокет мог слать оба события без всяких
    ограничений (см. security-скан: unthrottled WS handlers, CWE-770).
    Возвращает False и шлёт `error`, если лимит превышен."""
    try:
        await check_rate_limit(
            redis, bucket=bucket, key=str(user.id), limit=limit, window_seconds=window_seconds
        )
    except RateLimitExceeded:
        await _send_error(user.id, "rate_limited", f"too many {bucket} events, slow down")
        return False
    return True


async def _handle_message(user: User, event: ClientMessageEvent, db: AsyncSession, redis: Redis) -> None:
    if not await _check_ws_rate_limit(
        redis,
        user,
        bucket="ws_message",
        limit=settings.ws_message_rate_limit,
        window_seconds=settings.ws_message_rate_window_seconds,
    ):
        return

    room = await _get_room_or_error(db, user, event.payload.room_id)
    if room is None:
        return

    try:
        message = await send_message(
            db,
            room_id=room.id,
            sender_id=user.id,
            content=event.payload.content,
            content_type=event.payload.content_type,
        )
    except MessageRejected as exc:
        await _send_error(user.id, "message_rejected", exc.reason)
        return

    partner_id = room_manager.other_participant(room, user.id)
    await connection_manager.send_event(
        partner_id,
        ServerMessageEvent(
            payload=ServerMessagePayload(
                room_id=room.id,
                content=message.content,
                created_at=message.created_at.isoformat(),
            )
        ),
    )


async def _handle_typing(user: User, event: TypingEvent, db: AsyncSession, redis: Redis) -> None:
    if not await _check_ws_rate_limit(
        redis,
        user,
        bucket="ws_typing",
        limit=settings.ws_typing_rate_limit,
        window_seconds=settings.ws_typing_rate_window_seconds,
    ):
        return

    room = await _get_room_or_error(db, user, event.payload.room_id)
    if room is None:
        return
    partner_id = room_manager.other_participant(room, user.id)
    await connection_manager.send_event(
        partner_id,
        ServerTypingEvent(
            payload=ServerTypingPayload(room_id=room.id, is_typing=event.payload.is_typing)
        ),
    )


async def _handle_leave(
    user: User, event: LeaveEvent, db: AsyncSession, *, reason: EndReason
) -> None:
    room = await _get_room_or_error(db, user, event.payload.room_id)
    if room is None:
        return
    partner_id = room_manager.other_participant(room, user.id)
    await room_manager.end_room(db, room, reason=reason)
    await connection_manager.send_event(
        partner_id,
        PartnerLeftEvent(payload=PartnerLeftPayload(room_id=room.id, reason=reason.value)),
    )


async def handle_disconnect(user_id: uuid.UUID) -> None:
    """Реконнект: если пользователь был в активной комнате, даём grace-period
    (см. CLAUDE.md / project-structure.md 6.7) прежде чем закрывать комнату."""
    await asyncio.sleep(settings.room_reconnect_grace_seconds)
    if connection_manager.is_online(user_id):
        # Пользователь успел переподключиться — комната восстанавливается молча.
        return

    async with async_session_maker() as db:
        room = await room_manager.get_active_room_for_user(db, user_id)
        if room is None:
            return
        partner_id = room_manager.other_participant(room, user_id)
        await room_manager.end_room(db, room, reason=EndReason.TIMEOUT)
        await connection_manager.send_event(
            partner_id,
            PartnerLeftEvent(
                payload=PartnerLeftPayload(room_id=room.id, reason=EndReason.TIMEOUT.value)
            ),
        )


# ---------------------------------------------------------------------------
# Фоновый цикл матчинга
# ---------------------------------------------------------------------------


async def _notify_match(db: AsyncSession, redis: Redis, user1_id: str, user2_id: str, topic: str | None) -> None:
    u1 = await db.get(User, uuid.UUID(user1_id))
    u2 = await db.get(User, uuid.UUID(user2_id))
    if u1 is None or u2 is None:
        return

    room = await room_manager.create_room(db, user1_id=u1.id, user2_id=u2.id, topic=topic)

    # SearchSession — исторический след поиска: без этого он навсегда
    # остаётся в SEARCHING (см. код-ревью).
    await session_tracker.mark_matched(db, u1.id, room_id=room.id)
    await session_tracker.mark_matched(db, u2.id, room_id=room.id)

    await connection_manager.send_event(
        u1.id,
        MatchedEvent(
            payload=MatchedPayload(
                room_id=room.id,
                partner=PartnerInfo(gender=u2.gender, age_range=None, topic=topic),
            )
        ),
    )
    await connection_manager.send_event(
        u2.id,
        MatchedEvent(
            payload=MatchedPayload(
                room_id=room.id,
                partner=PartnerInfo(gender=u1.gender, age_range=None, topic=topic),
            )
        ),
    )


async def matchmaking_loop(redis: Redis, stop_event: asyncio.Event) -> None:
    """Фоновая задача: периодически ищет совместимые пары в очереди и создаёт комнаты.

    Запускается в lifespan приложения (app/main.py) и живёт всё время работы процесса.
    """
    interval = settings.match_loop_interval_seconds
    while not stop_event.is_set():
        try:
            match = await find_match(redis)
            if match is not None:
                async with async_session_maker() as db:
                    await _notify_match(db, redis, match.user1_id, match.user2_id, match.topic)
                continue  # сразу проверим ещё раз, вдруг очередь большая
        except Exception:  # noqa: BLE001 - цикл не должен падать целиком из-за одной ошибки
            logger.exception("matchmaking loop iteration failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
