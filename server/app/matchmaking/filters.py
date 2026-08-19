"""Совместимость фильтров двух кандидатов (тема/пол/возраст/роль в сюжете)."""

from typing import Any

from app.matchmaking.topics import PLOT_ROLE_TOPICS
from app.models.user import Gender


def _gender_ok(my_pref: str, other_gender: str) -> bool:
    return my_pref == Gender.UNSPECIFIED.value or my_pref == other_gender


def _age_ok(
    age_min: int | None,
    age_max: int | None,
    other_age: int | None,
    age_ranges: list[tuple[int, int]] | None = None,
) -> bool:
    """task190826_v2: если заданы несколько диапазонов возраста собеседника
    (множественный выбор чипов в "Общение"/"Флирт", минимум один) —
    достаточно попадания в ЛЮБОЙ из них. `age_min`/`age_max` остаются как
    легаси-фолбэк для записей без `age_ranges` (старые записи в очереди,
    несовместимые клиенты) — см. matchmaking/queue.py::QueueEntry.
    """
    if other_age is None:
        # Возраст не указан — не блокируем матч на этом основании.
        return True
    if age_ranges:
        return any(lo <= other_age <= hi for lo, hi in age_ranges)
    if age_min is not None and other_age < age_min:
        return False
    if age_max is not None and other_age > age_max:
        return False
    return True


def _topic_ok(a_topic: str | None, b_topic: str | None) -> bool:
    """Тема должна совпадать точно.

    Раньше "тема не выбрана" (falsy) трактовалась как wildcard — кандидат
    без темы считался совместимым с любой чужой темой, включая
    чувствительные (например, "Флирт 18+"), которую сам не выбирал. Это
    позволяло пользователю попасть в такую комнату без явного согласия
    (см. код-ревью: age-gate bypass). Теперь совместимы только одинаковые
    темы, включая случай "оба без темы" (None == None).
    """
    return a_topic == b_topic


def _plot_role_ok(topic: str | None, a_role: str | None, b_role: str | None) -> bool:
    """task190826: для темы "Ролка" роли должны быть комплементарны — один
    "ищет сюжет" (seeking_plot), другой "предлагает сюжет" (offering_plot).
    Для остальных тем поле не применяется и не блокирует матч."""
    if topic not in PLOT_ROLE_TOPICS:
        return True
    return bool(a_role) and bool(b_role) and a_role != b_role


def is_mutually_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """a, b — записи кандидатов из очереди (см. matchmaking/queue.py: QueueEntry.to_redis_hash).

    Совместимость взаимная: у обоих должны совпасть тема, предпочтения по
    полу/возрасту относительно друг друга, и (для тем из PLOT_ROLE_TOPICS)
    комплементарная роль в сюжете.
    """
    if not _topic_ok(a["topic"], b["topic"]):
        return False

    if not _gender_ok(a["partner_gender"], b["gender"]):
        return False
    if not _gender_ok(b["partner_gender"], a["gender"]):
        return False

    if not _age_ok(
        a["partner_age_min"], a["partner_age_max"], b["age"], a.get("partner_age_ranges")
    ):
        return False
    if not _age_ok(
        b["partner_age_min"], b["partner_age_max"], a["age"], b.get("partner_age_ranges")
    ):
        return False

    if not _plot_role_ok(a["topic"], a.get("plot_role"), b.get("plot_role")):
        return False

    return True
