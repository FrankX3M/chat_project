"""Пайплайн модерации контента (см. CLAUDE.md п.5).

Любое место, где сообщение попадает в БД или доставляется собеседнику,
обязано проходить через check_message() — без обхода, даже "временно для теста".

MVP-заглушка: реальные правила (маты/спам/ссылки/список запрещённых слов,
интеграция с внешним classifier) сюда добавляются позже. Пока фильтр
пропускает всё, но интерфейс и точка вызова уже зафиксированы, чтобы
дальнейшая логика подключалась без изменения message_service/event_handlers.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContentFilterResult:
    is_allowed: bool
    is_flagged: bool
    reason: str | None = None


async def check_message(content: str) -> ContentFilterResult:
    """Проверяет текст сообщения перед сохранением/доставкой.

    TODO(moderation): подключить реальные правила (запрещённые слова, спам,
    ссылки) и/или внешний content-moderation сервис. Сейчас всегда разрешает.
    """
    return ContentFilterResult(is_allowed=True, is_flagged=False)
