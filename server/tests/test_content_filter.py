"""Тесты moderation/content_filter.py — task190826: "Фильтровать пересылку
личных данных (телефоны, никнейки, почта)"."""

import pytest

from app.moderation.content_filter import check_message


@pytest.mark.asyncio
class TestContentFilter:
    async def test_plain_message_allowed(self):
        result = await check_message("привет, как дела?")
        assert result.is_allowed is True
        assert result.is_flagged is False

    async def test_email_blocked(self):
        result = await check_message("напиши мне на test.user@example.com")
        assert result.is_allowed is False
        assert result.is_flagged is True

    async def test_url_blocked(self):
        result = await check_message("го сюда https://example.com/room/123")
        assert result.is_allowed is False

    async def test_telegram_domain_blocked(self):
        result = await check_message("го в telegram t.me/someone")
        assert result.is_allowed is False

    async def test_mention_blocked(self):
        result = await check_message("пиши мне @cool_username")
        assert result.is_allowed is False

    async def test_phone_number_blocked(self):
        result = await check_message("звони +7 (999) 123-45-67")
        assert result.is_allowed is False

    async def test_phone_number_without_formatting_blocked(self):
        result = await check_message("мой номер 89991234567")
        assert result.is_allowed is False

    async def test_contact_keyword_blocked(self):
        result = await check_message("давай в телеграм общаться")
        assert result.is_allowed is False

    async def test_year_range_not_treated_as_phone(self):
        # Регрессия: диапазон вроде "2024-2025" не должен считаться телефоном
        # (недостаточно цифр).
        result = await check_message("это было в 2024-2025 годах")
        assert result.is_allowed is True

    async def test_short_numbers_not_blocked(self):
        result = await check_message("мне 25 лет, а тебе?")
        assert result.is_allowed is True
