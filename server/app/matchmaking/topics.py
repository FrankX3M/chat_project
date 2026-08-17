"""Темы, требующие подтверждения возраста перед постановкой в очередь.

Единый источник правды: и REST (`api/v1/search.py`), и WS
(`ws/event_handlers.py`) должны сверяться с этим списком, а не доверять
топику от клиента напрямую — иначе self-declaration в `PUT /settings`
ничего не гарантирует (см. код-ревью: age-gate bypass).
"""

# Значение соответствует topic-ключу, который присылает clients/web/index.html
# при выборе пилюли "Флирт 18+" (см. константу TOPICS в index.html).
FLIRT_18_PLUS_TOPIC = "flirt18"


def requires_age_verification(topic: str | None) -> bool:
    return topic == FLIRT_18_PLUS_TOPIC
