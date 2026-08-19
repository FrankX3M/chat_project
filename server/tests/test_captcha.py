"""Тесты moderation/captcha.py — task190826: простая антиспам-капча для
первых N сообщений. Без реальных сетевых вызовов к Google."""

import pytest

from app.moderation import captcha


@pytest.mark.asyncio
class TestVerificationsRemaining:
    async def test_full_threshold_when_never_verified(self, fake_redis):
        remaining = await captcha.verifications_remaining(fake_redis, "user-1", threshold=5)
        assert remaining == 5

    async def test_decreases_after_record_verified(self, fake_redis):
        await captcha.record_verified(fake_redis, "user-2")
        remaining = await captcha.verifications_remaining(fake_redis, "user-2", threshold=5)
        assert remaining == 4

    async def test_reaches_zero_and_does_not_go_negative(self, fake_redis):
        for _ in range(7):
            await captcha.record_verified(fake_redis, "user-3")
        remaining = await captcha.verifications_remaining(fake_redis, "user-3", threshold=5)
        assert remaining == 0

    async def test_counters_are_independent_per_user(self, fake_redis):
        await captcha.record_verified(fake_redis, "user-4")
        remaining_other = await captcha.verifications_remaining(
            fake_redis, "user-5", threshold=5
        )
        assert remaining_other == 5


@pytest.mark.asyncio
class TestVerifyRecaptcha:
    async def test_fails_closed_without_secret_key(self, monkeypatch):
        # settings.recaptcha_secret_key пуст по умолчанию (см. app/config.py) —
        # проверка невозможна физически, должна отклонять, а не пропускать.
        assert await captcha.verify_recaptcha("some-token") is False

    async def test_fails_closed_on_network_error(self, monkeypatch):
        from app.config import get_settings

        s = get_settings()
        monkeypatch.setattr(s, "recaptcha_secret_key", "test-secret")

        class _BoomClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, *args, **kwargs):
                raise captcha.httpx.ConnectError("network down")

        monkeypatch.setattr(captcha.httpx, "AsyncClient", _BoomClient)
        assert await captcha.verify_recaptcha("some-token") is False
