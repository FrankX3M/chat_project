from pydantic import BaseModel, Field, field_validator

from app.models.user import Gender


class UserSettingsResponse(BaseModel):
    # Собственный профиль (хранится на users, не на user_settings — см. models/user.py).
    gender: Gender = Gender.UNSPECIFIED
    age: int | None = None
    is_age_verified: bool = False

    # Настройки/фильтры поиска (user_settings).
    preferred_topic: str | None = None
    preferred_partner_gender: Gender = Gender.UNSPECIFIED
    preferred_age_min: int | None = None
    preferred_age_max: int | None = None
    color_theme: str | None = None
    is_18_plus_mode: bool = False

    model_config = {"from_attributes": True}


class UserSettingsUpdate(BaseModel):
    # Собственный профиль.
    gender: Gender = Gender.UNSPECIFIED
    age: int | None = Field(default=None, ge=13, le=120)
    # Самодекларация возраста для доступа к теме "Флирт 18+" (см. project-structure.md
    # 3.8, method=self_declaration). Полноценная KYC-верификация — вне MVP.
    self_declared_adult: bool = False

    # Настройки/фильтры поиска.
    preferred_topic: str | None = Field(default=None, max_length=64)
    preferred_partner_gender: Gender = Gender.UNSPECIFIED
    preferred_age_min: int | None = Field(default=None, ge=13, le=120)
    preferred_age_max: int | None = Field(default=None, ge=13, le=120)
    color_theme: str | None = Field(default=None, max_length=32)
    is_18_plus_mode: bool = False

    @field_validator("preferred_age_max")
    @classmethod
    def _check_age_range(cls, v: int | None, info):
        age_min = info.data.get("preferred_age_min")
        if v is not None and age_min is not None and v < age_min:
            raise ValueError("preferred_age_max must be >= preferred_age_min")
        return v
