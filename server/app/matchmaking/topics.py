"""Темы, требующие подтверждения возраста перед постановкой в очередь.

Единый источник правды: и REST (`api/v1/search.py`), и WS
(`ws/event_handlers.py`) должны сверяться с этим списком, а не доверять
топику от клиента напрямую — иначе self-declaration в `PUT /settings`
ничего не гарантирует (см. код-ревью: age-gate bypass).
"""

from app.models.user import Gender, PlotRole

# Значения соответствуют topic-ключам, которые присылает clients/web/index.html
# (см. константу TOPICS в index.html).
FLIRT_18_PLUS_TOPIC = "flirt18"
ROLEPLAY_TOPIC = "roleplay"

# task190826: "Флирт" и "Ролка" — пол собеседника можно выбрать только
# противоположный своему (никаких "неважно"/своего же пола).
OPPOSITE_GENDER_TOPICS = frozenset({FLIRT_18_PLUS_TOPIC, ROLEPLAY_TOPIC})

# task190826: "Ролка" — вкладка без возраста, фильтр по возрасту для неё не
# применяется вовсе (ни свой возраст, ни диапазон для собеседника).
NO_AGE_FILTER_TOPICS = frozenset({ROLEPLAY_TOPIC})

# task190826: "Ролка" — обязательный критерий "ищу сюжет"/"предлагаю сюжет".
PLOT_ROLE_TOPICS = frozenset({ROLEPLAY_TOPIC})


def requires_age_verification(topic: str | None) -> bool:
    return topic == FLIRT_18_PLUS_TOPIC


def requires_opposite_gender(topic: str | None) -> bool:
    return topic in OPPOSITE_GENDER_TOPICS


def excludes_age_filter(topic: str | None) -> bool:
    return topic in NO_AGE_FILTER_TOPICS


def requires_plot_role(topic: str | None) -> bool:
    return topic in PLOT_ROLE_TOPICS


def opposite_gender(gender: Gender) -> Gender | None:
    """Бинарная "противоположность" пола для тем из OPPOSITE_GENDER_TOPICS.

    UNSPECIFIED/OTHER не имеют однозначной противоположности — для таких
    own_gender вызывающая сторона должна отказать в выборе темы (см.
    validate_topic_selection), а не подставлять произвольное значение.
    """
    if gender == Gender.MALE:
        return Gender.FEMALE
    if gender == Gender.FEMALE:
        return Gender.MALE
    return None


def validate_topic_selection(
    topic: str | None,
    *,
    own_gender: Gender,
    partner_gender: Gender,
    plot_role: PlotRole | None,
) -> str | None:
    """Серверные инварианты по теме (см. task190826).

    Единая точка для REST (`api/v1/search.py`) и WS
    (`ws/event_handlers.py::_handle_join_queue`) — оба входа в очередь должны
    применять одну и ту же проверку, а не два похожих, но рассинхронизированных
    куска логики (тот же принцип, что и requires_age_verification выше).

    Возвращает текст ошибки, если тема выбрана некорректно, иначе None.
    """
    if requires_opposite_gender(topic):
        opp = opposite_gender(own_gender)
        if opp is None:
            return "specify your own gender (male/female) in settings to use this topic"
        if partner_gender != opp:
            return "only the opposite gender can be selected as partner for this topic"

    if requires_plot_role(topic) and plot_role is None:
        return "select a plot role (seeking_plot or offering_plot) for this topic"

    return None
