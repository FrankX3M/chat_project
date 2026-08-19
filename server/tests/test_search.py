"""Тесты REST /search/* — age-gate для чувствительных тем и переходы
статуса SearchSession (см. код-ревью: age-gate bypass, stale SearchSession).
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_redis_dep
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.matchmaking import queue as queue_repo
from app.models.search_session import SearchSession, SearchSessionStatus
from app.models.user import User


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


async def _create_user_and_token(
    db_session, device_id: str, *, age=None, is_age_verified=False, gender=None
) -> tuple[User, str]:
    user = User(device_id=device_id, age=age, is_age_verified=is_age_verified)
    if gender is not None:
        user.gender = gender
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user, create_access_token(user.id)


@pytest.mark.asyncio
class TestSearchAgeGate:
    async def test_flirt18_rejected_without_age_verification(self, db_session, api_client, fake_redis):
        _, token = await _create_user_and_token(db_session, "dev-search-1")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(
                "/api/v1/search/start", headers=headers, json={"topic": "flirt18"}
            )
        assert resp.status_code == 403

    async def test_flirt18_accepted_when_age_verified(self, db_session, api_client, fake_redis):
        user, token = await _create_user_and_token(
            db_session, "dev-search-2", age=25, is_age_verified=True, gender="male"
        )
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(
                "/api/v1/search/start",
                headers=headers,
                json={"topic": "flirt18", "partner_gender": "female"},
            )
        assert resp.status_code == 201
        assert await queue_repo.is_queued(fake_redis, user.id)

    async def test_general_topic_does_not_require_verification(self, db_session, api_client, fake_redis):
        _, token = await _create_user_and_token(db_session, "dev-search-3")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(
                "/api/v1/search/start", headers=headers, json={"topic": "general"}
            )
        assert resp.status_code == 201


@pytest.mark.asyncio
class TestSearchTopicConstraints:
    """task190826: "Флирт"/"Ролка" — только противоположный пол; "Ролка" — без
    возраста, обязателен plot_role. См. matchmaking/topics.py::validate_topic_selection."""

    async def test_flirt18_rejected_when_partner_gender_not_opposite(
        self, db_session, api_client, fake_redis
    ):
        _, token = await _create_user_and_token(
            db_session, "dev-search-4", age=25, is_age_verified=True, gender="male"
        )
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(
                "/api/v1/search/start",
                headers=headers,
                json={"topic": "flirt18", "partner_gender": "male"},
            )
        assert resp.status_code == 422

    async def test_flirt18_rejected_when_own_gender_unspecified(
        self, db_session, api_client, fake_redis
    ):
        _, token = await _create_user_and_token(
            db_session, "dev-search-5", age=25, is_age_verified=True
        )
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(
                "/api/v1/search/start",
                headers=headers,
                json={"topic": "flirt18", "partner_gender": "female"},
            )
        assert resp.status_code == 422

    async def test_roleplay_requires_plot_role(self, db_session, api_client, fake_redis):
        _, token = await _create_user_and_token(db_session, "dev-search-6", gender="male")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(
                "/api/v1/search/start",
                headers=headers,
                json={"topic": "roleplay", "partner_gender": "female"},
            )
        assert resp.status_code == 422

    async def test_roleplay_accepted_with_plot_role_and_opposite_gender(
        self, db_session, api_client, fake_redis
    ):
        user, token = await _create_user_and_token(db_session, "dev-search-7", gender="male")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(
                "/api/v1/search/start",
                headers=headers,
                json={
                    "topic": "roleplay",
                    "partner_gender": "female",
                    "plot_role": "seeking_plot",
                    "partner_age_min": 20,
                    "partner_age_max": 30,
                },
            )
        assert resp.status_code == 201

        entry_hash = await fake_redis.hgetall(f"queue:entry:{user.id}")
        # "Ролка" без возраста (task190826) — границы, присланные клиентом,
        # должны быть проигнорированы сервером, а не молча сохранены.
        assert entry_hash["partner_age_min"] == ""
        assert entry_hash["partner_age_max"] == ""
        assert entry_hash["plot_role"] == "seeking_plot"


@pytest.mark.asyncio
class TestSearchPartnerAgeRanges:
    """task190826_v2: множественный выбор диапазонов возраста собеседника
    ("Общение"/"Флирт" — минимум один диапазон на клиенте)."""

    async def test_multiple_ranges_stored_as_json_in_queue_entry(
        self, db_session, api_client, fake_redis
    ):
        user, token = await _create_user_and_token(db_session, "dev-search-8")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(
                "/api/v1/search/start",
                headers=headers,
                json={
                    "topic": "general",
                    "partner_age_ranges": [{"min": 18, "max": 21}, {"min": 36, "max": 99}],
                },
            )
        assert resp.status_code == 201

        entry_hash = await fake_redis.hgetall(f"queue:entry:{user.id}")
        assert json.loads(entry_hash["partner_age_ranges"]) == [[18, 21], [36, 99]]

    async def test_roleplay_ignores_partner_age_ranges_too(
        self, db_session, api_client, fake_redis
    ):
        user, token = await _create_user_and_token(db_session, "dev-search-9", gender="male")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(
                "/api/v1/search/start",
                headers=headers,
                json={
                    "topic": "roleplay",
                    "partner_gender": "female",
                    "plot_role": "seeking_plot",
                    "partner_age_ranges": [{"min": 18, "max": 21}],
                },
            )
        assert resp.status_code == 201

        entry_hash = await fake_redis.hgetall(f"queue:entry:{user.id}")
        assert entry_hash["partner_age_ranges"] == ""

    async def test_min_greater_than_max_rejected(self, db_session, api_client, fake_redis):
        _, token = await _create_user_and_token(db_session, "dev-search-10")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            resp = await client.post(
                "/api/v1/search/start",
                headers=headers,
                json={"topic": "general", "partner_age_ranges": [{"min": 30, "max": 20}]},
            )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestSearchSessionTracking:
    async def test_cancel_marks_session_cancelled(self, db_session, api_client, fake_redis):
        user, token = await _create_user_and_token(db_session, "dev-search-4")
        headers = {"Authorization": f"Bearer {token}"}
        async with api_client as client:
            await client.post("/api/v1/search/start", headers=headers, json={"topic": "general"})
            resp = await client.post("/api/v1/search/cancel", headers=headers)
        assert resp.status_code == 204

        result = await db_session.execute(select(SearchSession).where(SearchSession.user_id == user.id))
        session_row = result.scalars().one()
        assert session_row.status == SearchSessionStatus.CANCELLED
        assert not await queue_repo.is_queued(fake_redis, user.id)
