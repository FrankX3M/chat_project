"""POST /rooms/{id}/leave (REST) должен уведомлять партнёра по WS так же,
как WS-событие `leave` — иначе партнёр с открытым сокетом не узнаёт о
закрытии комнаты (см. код-ревью)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_redis_dep
from app.core.security import create_access_token
from app.chat import room_manager
from app.db.session import get_db
from app.main import app
from app.models.chat_room import ChatRoomStatus
from app.models.user import User
from app.ws.connection_manager import ConnectionManager


@pytest.fixture
def api_client(db_session, fake_redis):
    async def override_get_db():
        yield db_session

    async def override_get_redis():
        return fake_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis_dep] = override_get_redis
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, text):
        import json

        self.sent.append(json.loads(text))

    async def close(self, code=1000, reason=""):
        pass


async def _make_user(db_session, device_id: str) -> User:
    user = User(device_id=device_id)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
class TestLeaveRoom:
    async def test_rest_leave_notifies_partner_over_ws(self, db_session, api_client, monkeypatch):
        manager = ConnectionManager()
        monkeypatch.setattr("app.api.v1.rooms.connection_manager", manager)

        alice = await _make_user(db_session, "device-alice-rest")
        bob = await _make_user(db_session, "device-bob-rest")
        bob_ws = FakeWebSocket()
        await manager.connect(bob.id, bob_ws)

        room = await room_manager.create_room(db_session, user1_id=alice.id, user2_id=bob.id, topic="general")

        token = create_access_token(alice.id)
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(f"/api/v1/rooms/{room.id}/leave", headers=headers)
        assert resp.status_code == 204

        await db_session.refresh(room)
        assert room.status == ChatRoomStatus.ENDED

        assert len(bob_ws.sent) == 1
        assert bob_ws.sent[0]["event"] == "partner_left"
        assert bob_ws.sent[0]["payload"]["room_id"] == str(room.id)
