"""Простая антиспам-защита через Google reCAPTCHA (см. task190826):

"Подключить простую google capcha для первых 5-ти сообщений что бы избежать спама"

Выключено по умолчанию (`RECAPTCHA_ENABLED=false`, см. app/config.py) — тот же
принцип безопасного дефолта, что и для JWT_SECRET: пока оператор не задал
настоящие ключи от Google, фича не участвует в потоке вообще, а не тихо
пропускает всё как "проверено".

Счётчик пройденных проверок живёт в Redis (как online-counter/очередь
матчинга — см. CLAUDE.md п.3), не в Postgres: это не историческая запись, а
переиспользуемое runtime-состояние на пользователя.
"""

import logging
import uuid

import httpx
from redis.asyncio import Redis

from app.config import get_settings

logger = logging.getLogger(__name__)

GOOGLE_SITEVERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
_COUNTER_KEY_PREFIX = "captcha:verified_count:"


def _counter_key(user_id: uuid.UUID | str) -> str:
    return f"{_COUNTER_KEY_PREFIX}{user_id}"


async def verifications_remaining(
    redis: Redis, user_id: uuid.UUID | str, *, threshold: int | None = None
) -> int:
    """Сколько ещё сообщений этому пользователю нужно подтвердить капчей.

    0 — порог уже пройден, дальше капча не требуется.
    """
    settings = get_settings()
    effective_threshold = (
        settings.recaptcha_message_threshold if threshold is None else threshold
    )
    raw = await redis.get(_counter_key(user_id))
    count = int(raw) if raw else 0
    return max(0, effective_threshold - count)


async def record_verified(redis: Redis, user_id: uuid.UUID | str) -> None:
    """Засчитать успешно пройденную проверку — увеличивает счётчик навсегда
    (без TTL): "первые 5 сообщений" — это про весь срок жизни анонимного
    идентификатора, а не про одну комнату/сессию."""
    await redis.incr(_counter_key(user_id))


async def verify_recaptcha(token: str, *, remote_ip: str | None = None) -> bool:
    """Проверяет токен через Google siteverify API.

    Fail-closed: любая ошибка (нет секрета, таймаут, сеть, невалидный ответ)
    трактуется как "не прошёл", а не как "пропустить проверку" — иначе
    временная недоступность Google превращала бы антиспам-меру в дыру.
    """
    settings = get_settings()
    if not settings.recaptcha_secret_key:
        logger.warning(
            "recaptcha_enabled=true, но RECAPTCHA_SECRET_KEY пуст — "
            "проверка невозможна, отклоняем токен"
        )
        return False

    data = {"secret": settings.recaptcha_secret_key, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(GOOGLE_SITEVERIFY_URL, data=data)
            resp.raise_for_status()
            result = resp.json()
    except (httpx.HTTPError, ValueError):
        logger.exception("recaptcha siteverify request failed")
        return False

    return bool(result.get("success"))
