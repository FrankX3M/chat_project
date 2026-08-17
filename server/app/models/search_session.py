import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class SearchSessionStatus(StrEnum):
    SEARCHING = "searching"
    MATCHED = "matched"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class SearchSession(UUIDMixin, TimestampMixin, Base):
    """Запись о попытке поиска — для аналитики/отладки матчинга.

    Само состояние "в очереди" живёт в Redis (см. CLAUDE.md п.3), эта таблица —
    только исторический след.
    """

    __tablename__ = "search_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    topic: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # JSON общий тип + вариант JSONB на Postgres (индексируемость), но остаётся
    # совместимым с SQLite в юнит-тестах (см. tests/conftest.py).
    filters_snapshot: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )

    status: Mapped[SearchSessionStatus] = mapped_column(
        Enum(SearchSessionStatus, name="search_session_status"),
        default=SearchSessionStatus.SEARCHING,
    )

    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    room_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_rooms.id", ondelete="SET NULL"), nullable=True
    )
