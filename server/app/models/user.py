from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin, utcnow


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNSPECIFIED = "unspecified"


class UserStatus(StrEnum):
    ACTIVE = "active"
    BANNED = "banned"
    SHADOW_BANNED = "shadow_banned"


class PlotRole(StrEnum):
    """Критерий подбора для темы "Ролка" (см. task190826): пользователь либо
    ищет готовый сюжет, либо предлагает свой — матч допустим только между
    комплементарными ролями (см. matchmaking/filters.py::_plot_role_ok).
    Живёт здесь, а не в matchmaking/topics.py, по тому же принципу, что и
    Gender: маленькие переиспользуемые enum'ы — в models, а не размазаны по
    доменным модулям, которые на них ссылаются."""

    SEEKING = "seeking_plot"
    OFFERING = "offering_plot"


class User(UUIDMixin, TimestampMixin, Base):
    """Анонимный пользователь — идентифицируется по устройству, без регистрации."""

    __tablename__ = "users"

    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # Приватность по умолчанию: только хэш IP, сырой IP никогда не хранится (см. CLAUDE.md).
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_fingerprint_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    gender: Mapped[Gender] = mapped_column(
        Enum(Gender, name="gender"), default=Gender.UNSPECIFIED
    )
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_age_verified: Mapped[bool] = mapped_column(default=False)

    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status"), default=UserStatus.ACTIVE
    )

    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
