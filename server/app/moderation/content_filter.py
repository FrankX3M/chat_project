"""Пайплайн модерации контента (см. CLAUDE.md п.5).

Любое место, где сообщение попадает в БД или доставляется собеседнику,
обязано проходить через check_message() — без обхода, даже "временно для теста".

task190826: "Фильтровать пересылку личных данных (телефоны, никнейки, почта)" —
это же требование прямо повторяется в правилах каждого чата (см. рулесет в
clients/web/index.html): запрет на переход в сторонние мессенджеры/соцсети,
никнеймы, ссылки, обмен контактами. Реализовано простыми регулярками —
блокирует отправку сообщения целиком (а не тихо вырезает совпадение), чтобы
отправитель сразу видел причину через `error{code: message_rejected}` (см.
chat/message_service.py -> ws/event_handlers.py::_handle_message).

Дальнейшее усиление (маты/спам/внешний classifier) добавляется сюда же, не
меняя интерфейс check_message() и точку вызова.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ContentFilterResult:
    is_allowed: bool
    is_flagged: bool
    reason: str | None = None


# --- email -------------------------------------------------------------
_EMAIL_RE = re.compile(r"[a-zA-Z0-9][\w.+-]*@[a-zA-Z0-9][\w-]*\.[a-zA-Z]{2,}")

# --- ссылки и известные домены мессенджеров/соцсетей --------------------
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_MESSENGER_DOMAIN_RE = re.compile(
    r"\b(?:t\.me|telegram\.me|telegram\.org|tg://|wa\.me|whatsapp\.com|"
    r"instagram\.com|vk\.com|ok\.ru|discord\.gg|discord\.com|snapchat\.com|"
    r"facebook\.com|fb\.com|viber\.com)\b",
    re.IGNORECASE,
)

# --- @никнейм (telegram/instagram-стиль упоминания) ----------------------
_MENTION_RE = re.compile(r"(?<!\S)@[A-Za-z0-9_]{3,32}(?!\S)")

# --- телефон: последовательность из 7+ цифр, допускающая пробелы/дефисы/
# скобки/+ между ними, чтобы поймать варианты вида "+7 (999) 123-45-67",
# "8 999 123 45 67", "89991234567".
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)\+?\d[\d\-\s()]{6,17}\d(?!\w)")


def _digits_count(s: str) -> int:
    return sum(ch.isdigit() for ch in s)


def _looks_like_phone(candidate: str) -> bool:
    # Порог 9, а не 7: реальные номера (с кодом страны/без) — обычно 10-11
    # цифр, а диапазоны вроде "2024-2025" дают 8 цифр и не должны считаться
    # телефоном (см. tests/test_content_filter.py::test_year_range_not_treated_as_phone).
    return _digits_count(candidate) >= 9


# --- явные упоминания намерения передать контакт -------------------------
_CONTACT_KEYWORD_RE = re.compile(
    r"\b(?:никнейм|мой\s+ник|добавь(?:ся|те)?\s+в|давай\s+в\s+(?:телег|вотсап|вайбер)|"
    r"пиши\s+в\s+(?:телег|вотсап|вайбер|инст)|whatsapp|вотсап|вацап|телеграм(?:м)?|"
    r"инста(?:грам)?|вайбер|viber)\b",
    re.IGNORECASE,
)


async def check_message(content: str) -> ContentFilterResult:
    """Проверяет текст сообщения перед сохранением/доставкой.

    Блокирует (is_allowed=False) при обнаружении почты, ссылок/доменов
    мессенджеров и соцсетей, @никнеймов, телефонных номеров или явных
    упоминаний "давай в телеграм/вотсап" и т.п. — см. модуль-докстринг.
    """
    if _EMAIL_RE.search(content):
        return ContentFilterResult(
            is_allowed=False, is_flagged=True, reason="email addresses are not allowed"
        )

    if _URL_RE.search(content) or _MESSENGER_DOMAIN_RE.search(content):
        return ContentFilterResult(
            is_allowed=False,
            is_flagged=True,
            reason="links to other messengers or social networks are not allowed",
        )

    if _MENTION_RE.search(content):
        return ContentFilterResult(
            is_allowed=False, is_flagged=True, reason="usernames/handles are not allowed"
        )

    for match in _PHONE_CANDIDATE_RE.finditer(content):
        if _looks_like_phone(match.group()):
            return ContentFilterResult(
                is_allowed=False, is_flagged=True, reason="phone numbers are not allowed"
            )

    if _CONTACT_KEYWORD_RE.search(content):
        return ContentFilterResult(
            is_allowed=False,
            is_flagged=True,
            reason="sharing contact details / moving to another platform is not allowed",
        )

    return ContentFilterResult(is_allowed=True, is_flagged=False)
