"""Тесты matchmaking/topics.py — серверные инварианты по теме (task190826):
"Флирт"/"Ролка" — только противоположный пол; "Ролка" — без возраста,
обязателен plot_role."""

from app.matchmaking.topics import (
    excludes_age_filter,
    opposite_gender,
    requires_age_verification,
    requires_opposite_gender,
    requires_plot_role,
    validate_topic_selection,
)
from app.models.user import Gender, PlotRole


class TestOppositeGender:
    def test_male_opposite_is_female(self):
        assert opposite_gender(Gender.MALE) == Gender.FEMALE

    def test_female_opposite_is_male(self):
        assert opposite_gender(Gender.FEMALE) == Gender.MALE

    def test_unspecified_has_no_opposite(self):
        assert opposite_gender(Gender.UNSPECIFIED) is None

    def test_other_has_no_opposite(self):
        assert opposite_gender(Gender.OTHER) is None


class TestTopicPredicates:
    def test_flirt_requires_age_verification(self):
        assert requires_age_verification("flirt18") is True
        assert requires_age_verification("general") is False
        assert requires_age_verification("roleplay") is False

    def test_flirt_and_roleplay_require_opposite_gender(self):
        assert requires_opposite_gender("flirt18") is True
        assert requires_opposite_gender("roleplay") is True
        assert requires_opposite_gender("general") is False

    def test_only_roleplay_excludes_age_filter(self):
        assert excludes_age_filter("roleplay") is True
        assert excludes_age_filter("flirt18") is False
        assert excludes_age_filter("general") is False

    def test_only_roleplay_requires_plot_role(self):
        assert requires_plot_role("roleplay") is True
        assert requires_plot_role("flirt18") is False


class TestValidateTopicSelection:
    def test_general_topic_has_no_constraints(self):
        assert (
            validate_topic_selection(
                "general",
                own_gender=Gender.UNSPECIFIED,
                partner_gender=Gender.UNSPECIFIED,
                plot_role=None,
            )
            is None
        )

    def test_flirt_rejects_same_gender(self):
        error = validate_topic_selection(
            "flirt18", own_gender=Gender.MALE, partner_gender=Gender.MALE, plot_role=None
        )
        assert error is not None

    def test_flirt_rejects_unspecified_partner(self):
        error = validate_topic_selection(
            "flirt18",
            own_gender=Gender.MALE,
            partner_gender=Gender.UNSPECIFIED,
            plot_role=None,
        )
        assert error is not None

    def test_flirt_rejects_own_gender_unspecified(self):
        error = validate_topic_selection(
            "flirt18",
            own_gender=Gender.UNSPECIFIED,
            partner_gender=Gender.FEMALE,
            plot_role=None,
        )
        assert error is not None

    def test_flirt_accepts_opposite_gender(self):
        assert (
            validate_topic_selection(
                "flirt18",
                own_gender=Gender.MALE,
                partner_gender=Gender.FEMALE,
                plot_role=None,
            )
            is None
        )

    def test_roleplay_requires_plot_role_even_with_opposite_gender(self):
        error = validate_topic_selection(
            "roleplay", own_gender=Gender.MALE, partner_gender=Gender.FEMALE, plot_role=None
        )
        assert error is not None

    def test_roleplay_accepts_opposite_gender_and_plot_role(self):
        assert (
            validate_topic_selection(
                "roleplay",
                own_gender=Gender.FEMALE,
                partner_gender=Gender.MALE,
                plot_role=PlotRole.OFFERING,
            )
            is None
        )
