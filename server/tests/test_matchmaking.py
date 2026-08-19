import pytest

from app.matchmaking import queue as queue_repo
from app.matchmaking.filters import is_mutually_compatible
from app.matchmaking.matcher import find_match


def _entry(user_id, topic="", gender="unspecified", age="", partner_gender="unspecified",
           partner_age_min="", partner_age_max="", partner_age_ranges="", plot_role="",
           joined_at=None) -> queue_repo.QueueEntry:
    return queue_repo.QueueEntry(
        user_id=user_id,
        topic=topic,
        gender=gender,
        age=age,
        partner_gender=partner_gender,
        partner_age_min=partner_age_min,
        partner_age_max=partner_age_max,
        partner_age_ranges=partner_age_ranges,
        plot_role=plot_role,
        joined_at=joined_at if joined_at is not None else queue_repo.now_ts(),
    )


class TestFilters:
    def test_compatible_when_no_preferences(self):
        a = _entry("a").as_filter_dict()
        b = _entry("b").as_filter_dict()
        assert is_mutually_compatible(a, b)

    def test_incompatible_topic(self):
        a = _entry("a", topic="sport").as_filter_dict()
        b = _entry("b", topic="music").as_filter_dict()
        assert not is_mutually_compatible(a, b)

    def test_incompatible_gender_preference(self):
        a = _entry("a", partner_gender="female").as_filter_dict()
        b = _entry("b", gender="male").as_filter_dict()
        assert not is_mutually_compatible(a, b)

    def test_compatible_gender_preference(self):
        a = _entry("a", partner_gender="female").as_filter_dict()
        b = _entry("b", gender="female").as_filter_dict()
        assert is_mutually_compatible(a, b)

    def test_age_range_respected(self):
        a = _entry("a", partner_age_min="20", partner_age_max="30").as_filter_dict()
        b = _entry("b", age="35").as_filter_dict()
        assert not is_mutually_compatible(a, b)

    def test_age_unspecified_does_not_block(self):
        a = _entry("a", partner_age_min="20", partner_age_max="30").as_filter_dict()
        b = _entry("b", age="").as_filter_dict()
        assert is_mutually_compatible(a, b)

    # --- task190826_v2: множественный выбор диапазонов возраста собеседника ---

    def test_age_ranges_match_when_within_any_selected_range(self):
        # Выбраны непересекающиеся диапазоны 18-21 и 36+ ("Общение"/"Флирт" —
        # мультиселект чипов); партнёру 40 лет — попадает во второй диапазон.
        a = _entry("a", partner_age_ranges='[[18, 21], [36, 99]]').as_filter_dict()
        b = _entry("b", age="40").as_filter_dict()
        assert is_mutually_compatible(a, b)

    def test_age_ranges_reject_when_in_the_gap_between_ranges(self):
        # 27 лет не попадает ни в 18-21, ни в 36-99 — диапазоны не сплошные,
        # это не то же самое, что один диапазон 18-99.
        a = _entry("a", partner_age_ranges='[[18, 21], [36, 99]]').as_filter_dict()
        b = _entry("b", age="27").as_filter_dict()
        assert not is_mutually_compatible(a, b)

    def test_age_ranges_take_priority_over_legacy_min_max(self):
        # Если оба поля присутствуют (не должно происходить у актуального
        # клиента, но защищаемся от рассинхрона) — только ranges считает.
        a = _entry(
            "a", partner_age_min="20", partner_age_max="30", partner_age_ranges='[[40, 50]]'
        ).as_filter_dict()
        b = _entry("b", age="45").as_filter_dict()
        assert is_mutually_compatible(a, b)

    def test_age_ranges_empty_falls_back_to_legacy_min_max(self):
        # Старые записи в очереди (до появления partner_age_ranges) не должны
        # начать пропускать всех подряд — легаси-фолбэк обязателен.
        a = _entry("a", partner_age_min="20", partner_age_max="30", partner_age_ranges="").as_filter_dict()
        b = _entry("b", age="45").as_filter_dict()
        assert not is_mutually_compatible(a, b)

    def test_age_ranges_malformed_json_does_not_crash_and_falls_back(self):
        a = _entry(
            "a", partner_age_min="20", partner_age_max="30", partner_age_ranges="not-json"
        ).as_filter_dict()
        assert a["partner_age_ranges"] == []
        b = _entry("b", age="25").as_filter_dict()
        assert is_mutually_compatible(a, b)

    def test_topic_must_match_exactly_not_treated_as_wildcard(self):
        # Раньше "тема не выбрана" у одного из кандидатов трактовалась как
        # wildcard, и они матчились с любой чужой темой — включая
        # чувствительные (см. код-ревью: age-gate bypass).
        a = _entry("a", topic="flirt18").as_filter_dict()
        b = _entry("b", topic="").as_filter_dict()
        assert not is_mutually_compatible(a, b)

    def test_both_without_topic_are_compatible(self):
        a = _entry("a", topic="").as_filter_dict()
        b = _entry("b", topic="").as_filter_dict()
        assert is_mutually_compatible(a, b)

    # --- task190826: критерий "ищу/предлагаю сюжет" для темы "roleplay" ---

    def test_roleplay_incompatible_when_same_plot_role(self):
        a = _entry("a", topic="roleplay", plot_role="seeking_plot").as_filter_dict()
        b = _entry("b", topic="roleplay", plot_role="seeking_plot").as_filter_dict()
        assert not is_mutually_compatible(a, b)

    def test_roleplay_compatible_when_complementary_plot_role(self):
        a = _entry("a", topic="roleplay", plot_role="seeking_plot").as_filter_dict()
        b = _entry("b", topic="roleplay", plot_role="offering_plot").as_filter_dict()
        assert is_mutually_compatible(a, b)

    def test_roleplay_incompatible_when_plot_role_missing(self):
        a = _entry("a", topic="roleplay", plot_role="seeking_plot").as_filter_dict()
        b = _entry("b", topic="roleplay", plot_role="").as_filter_dict()
        assert not is_mutually_compatible(a, b)

    def test_plot_role_ignored_outside_roleplay_topic(self):
        # Одинаковый plot_role вне темы "roleplay" не должен ничего блокировать.
        a = _entry("a", topic="general", plot_role="seeking_plot").as_filter_dict()
        b = _entry("b", topic="general", plot_role="seeking_plot").as_filter_dict()
        assert is_mutually_compatible(a, b)


@pytest.mark.asyncio
class TestQueueAndMatcher:
    async def test_enqueue_dequeue_position(self, fake_redis):
        await queue_repo.enqueue(fake_redis, _entry("u1", joined_at=1.0))
        await queue_repo.enqueue(fake_redis, _entry("u2", joined_at=2.0))

        assert await queue_repo.is_queued(fake_redis, "u1")
        assert await queue_repo.get_position(fake_redis, "u1") == 1
        assert await queue_repo.get_position(fake_redis, "u2") == 2

        await queue_repo.dequeue(fake_redis, "u1")
        assert not await queue_repo.is_queued(fake_redis, "u1")

    async def test_find_match_compatible_pair(self, fake_redis):
        await queue_repo.enqueue(fake_redis, _entry("u1", topic="sport", joined_at=1.0))
        await queue_repo.enqueue(fake_redis, _entry("u2", topic="sport", joined_at=2.0))

        result = await find_match(fake_redis)

        assert result is not None
        assert {result.user1_id, result.user2_id} == {"u1", "u2"}
        assert result.topic == "sport"
        # Оба должны быть убраны из очереди после матча.
        assert not await queue_repo.is_queued(fake_redis, "u1")
        assert not await queue_repo.is_queued(fake_redis, "u2")

    async def test_find_match_returns_none_for_incompatible(self, fake_redis):
        await queue_repo.enqueue(fake_redis, _entry("u1", topic="sport", joined_at=1.0))
        await queue_repo.enqueue(fake_redis, _entry("u2", topic="music", joined_at=2.0))

        result = await find_match(fake_redis)

        assert result is None
        assert await queue_repo.is_queued(fake_redis, "u1")
        assert await queue_repo.is_queued(fake_redis, "u2")

    async def test_find_match_returns_none_for_single_candidate(self, fake_redis):
        await queue_repo.enqueue(fake_redis, _entry("u1", joined_at=1.0))
        assert await find_match(fake_redis) is None
