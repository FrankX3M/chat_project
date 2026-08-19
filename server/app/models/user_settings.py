import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow
from app.models.user import Gender, PlotRole


class UserSettings(Base):
    """1:1 с users — текущие фильтры/настройки поиска и UI-предпочтения."""

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    preferred_topic: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preferred_partner_gender: Mapped[Gender] = mapped_column(
        Enum(Gender, name="gender"), default=Gender.UNSPECIFIED
    )
    preferred_age_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferred_age_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # task190826: критерий "ищу/предлагаю сюжет" для темы "Ролка".
    preferred_plot_role: Mapped[PlotRole | None] = mapped_column(
        Enum(PlotRole, name="plot_role"), nullable=True
    )
    color_theme: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Требует is_age_verified=true — не ослаблять эту проверку (см. CLAUDE.md п.6).
    is_18_plus_mode: Mapped[bool] = mapped_column(default=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
