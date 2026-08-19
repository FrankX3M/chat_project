import uuid
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from app.models.user import Gender, PlotRole


class AgeRange(BaseModel):
    """Один диапазон возраста собеседника (одна выбранная вкладка-чип)."""

    min: int = Field(ge=13, le=120)
    max: int = Field(ge=13, le=120)

    @model_validator(mode="after")
    def _check_order(self) -> "AgeRange":
        if self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class SearchStartRequest(BaseModel):
    topic: str | None = Field(default=None, max_length=64)
    partner_gender: Gender = Gender.UNSPECIFIED
    # Легаси-поля: одиночный диапазон, оставлены для обратной совместимости
    # (аналитика в filters_snapshot, старые/несовместимые клиенты). Актуальный
    # источник правды для матчинга при множественном выборе — partner_age_ranges
    # ниже (см. app.matchmaking.filters._age_ok).
    partner_age_min: int | None = Field(default=None, ge=13, le=120)
    partner_age_max: int | None = Field(default=None, ge=13, le=120)
    # task190826_v2: во вкладках "Общение"/"Флирт" возраст собеседника — это
    # множественный выбор (минимум один диапазон). Пустой список трактуется
    # как "фильтр не задан" (совместимо с legacy partner_age_min/max выше).
    partner_age_ranges: list[AgeRange] = Field(default_factory=list)
    # task190826: критерий "ищу сюжет"/"предлагаю сюжет" — обязателен только
    # для темы "Ролка" (см. matchmaking/topics.py::requires_plot_role).
    plot_role: PlotRole | None = None


class SearchStatusValue(StrEnum):
    IDLE = "idle"
    SEARCHING = "searching"
    MATCHED = "matched"


class SearchStatusResponse(BaseModel):
    status: SearchStatusValue
    room_id: uuid.UUID | None = None
    queue_position: int | None = None
