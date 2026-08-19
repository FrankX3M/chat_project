"""Тесты PUT/GET /settings (собственный профиль + самодекларация 18+) и
GET /stats/online — через реальный ASGI-стек FastAPI (роутинг, валидация,
Depends), с подменой БД/Redis на тестовые (см. conftest.py).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_redis_dep
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
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


async def _create_user_and_token(db_session, device_id: str) -> str:
    user = User(device_id=device_id)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return create_access_token(user.id)


@pytest.mark.asyncio
class TestSettingsEndpoint:
    async def test_own_profile_and_preferences_persist(self, db_session, api_client):
        token = await _create_user_and_token(db_session, "dev-1")
        headers = {"Authorization": f"Bearer {token}"}

        async with api_client as client:
            resp = await client.put(
                "/api/v1/settings",
                headers=headers,
                json={
                    "gender": "male",
                    "age": 25,
                    "preferred_topic": "general",
                    "preferred_partner_gender": "female",
                    "preferred_age_min": 20,
                    "preferred_age_max": 30,
                    "color_theme": "dark",
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["gender"] == "male"
            assert body["age"] == 25
            assert body["preferred_partner_gender"] == "female"
            # task190826: возраст >= 18 сам по себе — самодекларация совершеннолетия
            # (отдельный чекбокс убран из UI), поэтому is_age_verified уже True.
            assert body["is_age_verified"] is True

            # GET должен вернуть ровно то же, что только что сохранили.
            get_resp = await client.get("/api/v1/settings", headers=headers)
            assert get_resp.status_code == 200
            assert get_resp.json() == body

    async def test_flirt18_rejected_when_underage(self, db_session, api_client):
        # task190826: отдельный чекбокс "подтверждаю, что мне есть 18" убран из
        # UI — самодекларация теперь просто "age >= 18", без self_declared_adult.
        token = await _create_user_and_token(db_session, "dev-2")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.put(
                "/api/v1/settings",
                headers=headers,
                json={"gender": "unspecified", "age": 15, "is_18_plus_mode": True},
            )
        assert resp.status_code == 422

    async def test_flirt18_accepted_when_age_18_or_older(self, db_session, api_client):
        # Без self_declared_adult в теле запроса вовсе — по task190826 сам факт
        # выбора возраста от 18 лет уже считается самодекларацией.
        token = await _create_user_and_token(db_session, "dev-3")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.put(
                "/api/v1/settings",
                headers=headers,
                json={"gender": "unspecified", "age": 25, "is_18_plus_mode": True},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_age_verified"] is True
        assert body["is_18_plus_mode"] is True

    async def test_flirt18_rejected_if_underage_even_with_legacy_checkbox_field(
        self, db_session, api_client
    ):
        # self_declared_adult остаётся в схеме ради обратной совместимости, но
        # больше ни на что не влияет — возраст ниже 18 всё равно отклоняется.
        token = await _create_user_and_token(db_session, "dev-4")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.put(
                "/api/v1/settings",
                headers=headers,
                json={
                    "gender": "unspecified",
                    "age": 15,
                    "self_declared_adult": True,
                    "is_18_plus_mode": True,
                },
            )
        assert resp.status_code == 422

    async def test_roleplay_plot_role_preference_persists(self, db_session, api_client):
        token = await _create_user_and_token(db_session, "dev-5")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.put(
                "/api/v1/settings",
                headers=headers,
                json={
                    "gender": "male",
                    "preferred_topic": "roleplay",
                    "preferred_partner_gender": "female",
                    "preferred_plot_role": "seeking_plot",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["preferred_plot_role"] == "seeking_plot"

    async def test_requires_auth(self, api_client):
        async with api_client as client:
            resp = await client.get("/api/v1/settings")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestStatsEndpoint:
    async def test_online_count_reflects_connections(self, api_client, monkeypatch):
        manager = ConnectionManager()
        monkeypatch.setattr("app.api.v1.stats.connection_manager", manager)

        class FakeWs:
            async def accept(self):
                pass

        await manager.connect(uuid.uuid4(), FakeWs())
        await manager.connect(uuid.uuid4(), FakeWs())

        async with api_client as client:
            resp = await client.get("/api/v1/stats/online")
        assert resp.status_code == 200
        assert resp.json()["online"] == 2

    async def test_online_count_zero_by_default(self, api_client, monkeypatch):
        manager = ConnectionManager()
        monkeypatch.setattr("app.api.v1.stats.connection_manager", manager)

        async with api_client as client:
            resp = await client.get("/api/v1/stats/online")
        assert resp.status_code == 200
        assert resp.json()["online"] == 0
