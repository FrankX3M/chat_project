"""Интеграционный тест WS-флоу: поиск -> матч -> чат -> leave.

Гоняем через event_handlers/connection_manager напрямую (с фейковым
WebSocket-приёмником), без поднятия реального ASGI/Postgres/Redis — это
делает тест быстрым и детерминированным, при этом покрывает ровно тот путь,
что описан в project-structure.md (раздел 6.2-6.4) и CLAUDE.md.
"""

import json
import uuid

import pytest

from app.chat.room_manager import get_room
from app.matchmaking import queue as queue_repo
from app.matchmaking.matcher import find_match
from app.models.chat_room import ChatRoomStatus, EndReason
from app.models.search_session import SearchSession, SearchSessionStatus
from app.models.user import User
from app.schemas.ws_events import (
    ClientMessageEvent,
    ClientMessagePayload,
    JoinQueueEvent,
    JoinQueuePayload,
    LeaveEvent,
    LeavePayload,
    TypingEvent,
    TypingPayload,
)
from app.ws import event_handlers
from app.ws.connection_manager import ConnectionManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False

    async def accept(self) -> None:
        pass

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True


@pytest.fixture
def isolated_connection_manager(monkeypatch):
    """Свежий ConnectionManager на каждый тест — глобальный singleton не шарим между тестами."""
    manager = ConnectionManager()
    monkeypatch.setattr(event_handlers, "connection_manager", manager)
    monkeypatch.setattr("app.ws.connection_manager.connection_manager", manager)
    return manager


async def _make_user(db_session, device_id: str, gender: str = "unspecified", age: int | None = None) -> User:
    user = User(device_id=device_id, gender=gender, age=age)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _fake_verify_recaptcha_ok(token: str, *, remote_ip: str | None = None) -> bool:
    """Заглушка для тестов — не ходит в сеть к Google."""
    return bool(token)


@pytest.mark.asyncio
class TestWsFlow:
    async def test_full_flow_search_chat_leave(self, db_session, fake_redis, isolated_connection_manager):
        manager = isolated_connection_manager

        alice = await _make_user(db_session, "device-alice", gender="female", age=25)
        bob = await _make_user(db_session, "device-bob", gender="male", age=27)

        alice_ws, bob_ws = FakeWebSocket(), FakeWebSocket()
        await manager.connect(alice.id, alice_ws)
        await manager.connect(bob.id, bob_ws)

        # --- 1. Поиск: оба встают в очередь с совместимыми фильтрами ---
        await queue_repo.enqueue(
            fake_redis,
            queue_repo.QueueEntry(
                user_id=str(alice.id), topic="movies", gender="female", age="25",
                partner_gender="unspecified", partner_age_min="", partner_age_max="",
                joined_at=1.0,
            ),
        )
        await queue_repo.enqueue(
            fake_redis,
            queue_repo.QueueEntry(
                user_id=str(bob.id), topic="movies", gender="male", age="27",
                partner_gender="unspecified", partner_age_min="", partner_age_max="",
                joined_at=2.0,
            ),
        )

        match = await find_match(fake_redis)
        assert match is not None
        assert not await queue_repo.is_queued(fake_redis, str(alice.id))
        assert not await queue_repo.is_queued(fake_redis, str(bob.id))

        # --- 2. Матч создаёт комнату и рассылает `matched` обоим ---
        await event_handlers._notify_match(db_session, fake_redis, match.user1_id, match.user2_id, match.topic)

        assert len(alice_ws.sent) == 1 and alice_ws.sent[0]["event"] == "matched"
        assert len(bob_ws.sent) == 1 and bob_ws.sent[0]["event"] == "matched"
        room_id = uuid.UUID(alice_ws.sent[0]["payload"]["room_id"])
        assert room_id == uuid.UUID(bob_ws.sent[0]["payload"]["room_id"])

        room = await get_room(db_session, room_id)
        assert room is not None
        assert room.status == ChatRoomStatus.ACTIVE

        # --- 3. Чат: сообщение и typing долетают собеседнику ---
        msg_event = ClientMessageEvent(
            payload=ClientMessagePayload(room_id=room_id, content="привет!")
        )
        await event_handlers.dispatch_event(alice, msg_event, db_session, fake_redis)

        assert len(bob_ws.sent) == 2
        assert bob_ws.sent[-1]["event"] == "message"
        assert bob_ws.sent[-1]["payload"]["content"] == "привет!"
        assert bob_ws.sent[-1]["payload"]["sender"] == "partner"
        # Отправителю эхо не шлём.
        assert len(alice_ws.sent) == 1

        typing_event = TypingEvent(payload=TypingPayload(room_id=room_id, is_typing=True))
        await event_handlers.dispatch_event(alice, typing_event, db_session, fake_redis)
        assert bob_ws.sent[-1]["event"] == "typing"
        assert bob_ws.sent[-1]["payload"]["is_typing"] is True

        # --- 4. Leave: комната закрывается, партнёр уведомлён ---
        leave_event = LeaveEvent(payload=LeavePayload(room_id=room_id))
        await event_handlers.dispatch_event(alice, leave_event, db_session, fake_redis)

        await db_session.refresh(room)
        assert room.status == ChatRoomStatus.ENDED
        assert room.end_reason == EndReason.USER_LEFT

        assert bob_ws.sent[-1]["event"] == "partner_left"
        assert bob_ws.sent[-1]["payload"]["room_id"] == str(room_id)

    async def test_message_to_foreign_room_is_rejected(self, db_session, fake_redis, isolated_connection_manager):
        manager = isolated_connection_manager
        alice = await _make_user(db_session, "device-alice-2")
        alice_ws = FakeWebSocket()
        await manager.connect(alice.id, alice_ws)

        fake_room_id = uuid.uuid4()
        event = ClientMessageEvent(payload=ClientMessagePayload(room_id=fake_room_id, content="hi"))
        await event_handlers.dispatch_event(alice, event, db_session, fake_redis)

        assert alice_ws.sent[-1]["event"] == "error"
        assert alice_ws.sent[-1]["payload"]["code"] == "room_not_found"

    async def test_join_queue_flirt18_rejected_without_age_verification(
        self, db_session, fake_redis, isolated_connection_manager
    ):
        alice = await _make_user(db_session, "device-alice-3")
        alice_ws = FakeWebSocket()
        await isolated_connection_manager.connect(alice.id, alice_ws)

        event = JoinQueueEvent(payload=JoinQueuePayload(topic="flirt18"))
        await event_handlers.dispatch_event(alice, event, db_session, fake_redis)

        assert alice_ws.sent[-1]["event"] == "error"
        assert alice_ws.sent[-1]["payload"]["code"] == "age_verification_required"
        assert not await queue_repo.is_queued(fake_redis, alice.id)

    async def test_join_queue_flirt18_accepted_when_age_verified(
        self, db_session, fake_redis, isolated_connection_manager
    ):
        # task190826: "Флирт" требует противоположный пол — alice=female, поэтому
        # partner_gender должен быть male.
        alice = User(device_id="device-alice-4", age=25, is_age_verified=True, gender="female")
        db_session.add(alice)
        await db_session.commit()
        await db_session.refresh(alice)
        alice_ws = FakeWebSocket()
        await isolated_connection_manager.connect(alice.id, alice_ws)

        event = JoinQueueEvent(payload=JoinQueuePayload(topic="flirt18", partner_gender="male"))
        await event_handlers.dispatch_event(alice, event, db_session, fake_redis)

        assert await queue_repo.is_queued(fake_redis, alice.id)

    async def test_join_queue_flirt18_rejected_when_partner_gender_not_opposite(
        self, db_session, fake_redis, isolated_connection_manager
    ):
        alice = User(device_id="device-alice-3b", age=25, is_age_verified=True, gender="female")
        db_session.add(alice)
        await db_session.commit()
        await db_session.refresh(alice)
        alice_ws = FakeWebSocket()
        await isolated_connection_manager.connect(alice.id, alice_ws)

        event = JoinQueueEvent(payload=JoinQueuePayload(topic="flirt18", partner_gender="female"))
        await event_handlers.dispatch_event(alice, event, db_session, fake_redis)

        assert alice_ws.sent[-1]["event"] == "error"
        assert alice_ws.sent[-1]["payload"]["code"] == "invalid_topic_filters"
        assert not await queue_repo.is_queued(fake_redis, alice.id)

    async def test_join_queue_roleplay_requires_plot_role(
        self, db_session, fake_redis, isolated_connection_manager
    ):
        alice = await _make_user(db_session, "device-alice-roleplay", gender="male")
        alice_ws = FakeWebSocket()
        await isolated_connection_manager.connect(alice.id, alice_ws)

        event = JoinQueueEvent(payload=JoinQueuePayload(topic="roleplay", partner_gender="female"))
        await event_handlers.dispatch_event(alice, event, db_session, fake_redis)

        assert alice_ws.sent[-1]["event"] == "error"
        assert alice_ws.sent[-1]["payload"]["code"] == "invalid_topic_filters"
        assert not await queue_repo.is_queued(fake_redis, alice.id)

    async def test_notify_match_marks_search_sessions_matched(
        self, db_session, fake_redis, isolated_connection_manager
    ):
        alice = await _make_user(db_session, "device-alice-5")
        bob = await _make_user(db_session, "device-bob-2")
        await isolated_connection_manager.connect(alice.id, FakeWebSocket())
        await isolated_connection_manager.connect(bob.id, FakeWebSocket())

        alice_session = SearchSession(
            user_id=alice.id, topic="movies", filters_snapshot={}, status=SearchSessionStatus.SEARCHING
        )
        bob_session = SearchSession(
            user_id=bob.id, topic="movies", filters_snapshot={}, status=SearchSessionStatus.SEARCHING
        )
        db_session.add_all([alice_session, bob_session])
        await db_session.commit()

        await event_handlers._notify_match(db_session, fake_redis, str(alice.id), str(bob.id), "movies")

        await db_session.refresh(alice_session)
        await db_session.refresh(bob_session)
        assert alice_session.status == SearchSessionStatus.MATCHED
        assert alice_session.matched_at is not None
        assert alice_session.room_id is not None
        assert bob_session.status == SearchSessionStatus.MATCHED
        assert bob_session.room_id == alice_session.room_id

    async def test_message_flood_is_rate_limited(
        self, db_session, fake_redis, isolated_connection_manager, monkeypatch
    ):
        # Раньше `message`/`typing` не были ничем ограничены — один сокет мог
        # заваливать партнёра/БД без лимита (см. security-скан, CWE-770).
        monkeypatch.setattr(event_handlers.settings, "ws_message_rate_limit", 3)
        monkeypatch.setattr(event_handlers.settings, "ws_message_rate_window_seconds", 60)

        alice = await _make_user(db_session, "device-alice-flood")
        bob = await _make_user(db_session, "device-bob-flood")
        alice_ws, bob_ws = FakeWebSocket(), FakeWebSocket()
        await isolated_connection_manager.connect(alice.id, alice_ws)
        await isolated_connection_manager.connect(bob.id, bob_ws)

        room = await event_handlers.room_manager.create_room(
            db_session, user1_id=alice.id, user2_id=bob.id, topic="general"
        )

        for _ in range(3):
            event = ClientMessageEvent(payload=ClientMessagePayload(room_id=room.id, content="hi"))
            await event_handlers.dispatch_event(alice, event, db_session, fake_redis)
        assert len(bob_ws.sent) == 3  # первые 3 в пределах лимита долетели

        # 4-е сообщение в том же окне — отклонено, до партнёра не долетает.
        event = ClientMessageEvent(payload=ClientMessagePayload(room_id=room.id, content="spam"))
        await event_handlers.dispatch_event(alice, event, db_session, fake_redis)

        assert len(bob_ws.sent) == 3
        assert alice_ws.sent[-1]["event"] == "error"
        assert alice_ws.sent[-1]["payload"]["code"] == "rate_limited"

    async def test_message_requires_captcha_when_enabled_and_threshold_not_met(
        self, db_session, fake_redis, isolated_connection_manager, monkeypatch
    ):
        # task190826: пока капча включена и порог не пройден — сообщение без
        # captcha_token отклоняется, до партнёра не долетает.
        monkeypatch.setattr(event_handlers.settings, "recaptcha_enabled", True)

        alice = await _make_user(db_session, "device-alice-captcha-1")
        bob = await _make_user(db_session, "device-bob-captcha-1")
        alice_ws, bob_ws = FakeWebSocket(), FakeWebSocket()
        await isolated_connection_manager.connect(alice.id, alice_ws)
        await isolated_connection_manager.connect(bob.id, bob_ws)

        room = await event_handlers.room_manager.create_room(
            db_session, user1_id=alice.id, user2_id=bob.id, topic="general"
        )

        event = ClientMessageEvent(payload=ClientMessagePayload(room_id=room.id, content="hi"))
        await event_handlers.dispatch_event(alice, event, db_session, fake_redis)

        assert len(bob_ws.sent) == 0
        assert alice_ws.sent[-1]["event"] == "error"
        assert alice_ws.sent[-1]["payload"]["code"] == "captcha_required"

    async def test_message_delivered_with_valid_captcha_token(
        self, db_session, fake_redis, isolated_connection_manager, monkeypatch
    ):
        monkeypatch.setattr(event_handlers.settings, "recaptcha_enabled", True)
        monkeypatch.setattr(
            event_handlers.captcha_service, "verify_recaptcha", _fake_verify_recaptcha_ok
        )

        alice = await _make_user(db_session, "device-alice-captcha-2")
        bob = await _make_user(db_session, "device-bob-captcha-2")
        alice_ws, bob_ws = FakeWebSocket(), FakeWebSocket()
        await isolated_connection_manager.connect(alice.id, alice_ws)
        await isolated_connection_manager.connect(bob.id, bob_ws)

        room = await event_handlers.room_manager.create_room(
            db_session, user1_id=alice.id, user2_id=bob.id, topic="general"
        )

        event = ClientMessageEvent(
            payload=ClientMessagePayload(room_id=room.id, content="hi", captcha_token="tok")
        )
        await event_handlers.dispatch_event(alice, event, db_session, fake_redis)

        assert len(bob_ws.sent) == 1
        assert bob_ws.sent[-1]["event"] == "message"

    async def test_message_no_captcha_needed_once_disabled(
        self, db_session, fake_redis, isolated_connection_manager, monkeypatch
    ):
        # Дефолт (RECAPTCHA_ENABLED=false) — фича вне потока вообще, поведение
        # не меняется по сравнению с тем, что было до task190826.
        alice = await _make_user(db_session, "device-alice-captcha-3")
        bob = await _make_user(db_session, "device-bob-captcha-3")
        alice_ws, bob_ws = FakeWebSocket(), FakeWebSocket()
        await isolated_connection_manager.connect(alice.id, alice_ws)
        await isolated_connection_manager.connect(bob.id, bob_ws)

        room = await event_handlers.room_manager.create_room(
            db_session, user1_id=alice.id, user2_id=bob.id, topic="general"
        )

        event = ClientMessageEvent(payload=ClientMessagePayload(room_id=room.id, content="hi"))
        await event_handlers.dispatch_event(alice, event, db_session, fake_redis)

        assert len(bob_ws.sent) == 1
        assert bob_ws.sent[-1]["event"] == "message"

    async def test_typing_flood_is_rate_limited(
        self, db_session, fake_redis, isolated_connection_manager, monkeypatch
    ):
        monkeypatch.setattr(event_handlers.settings, "ws_typing_rate_limit", 2)
        monkeypatch.setattr(event_handlers.settings, "ws_typing_rate_window_seconds", 60)

        alice = await _make_user(db_session, "device-alice-typing-flood")
        bob = await _make_user(db_session, "device-bob-typing-flood")
        alice_ws, bob_ws = FakeWebSocket(), FakeWebSocket()
        await isolated_connection_manager.connect(alice.id, alice_ws)
        await isolated_connection_manager.connect(bob.id, bob_ws)

        room = await event_handlers.room_manager.create_room(
            db_session, user1_id=alice.id, user2_id=bob.id, topic="general"
        )

        for _ in range(2):
            event = TypingEvent(payload=TypingPayload(room_id=room.id, is_typing=True))
            await event_handlers.dispatch_event(alice, event, db_session, fake_redis)
        assert len(bob_ws.sent) == 2

        event = TypingEvent(payload=TypingPayload(room_id=room.id, is_typing=True))
        await event_handlers.dispatch_event(alice, event, db_session, fake_redis)

        assert len(bob_ws.sent) == 2
        assert alice_ws.sent[-1]["event"] == "error"
        assert alice_ws.sent[-1]["payload"]["code"] == "rate_limited"
