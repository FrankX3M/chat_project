import uuid
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ContentType(StrEnum):
    TEXT = "text"
    EMOJI = "emoji"
    SYSTEM = "system"


class Message(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "messages"

    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_rooms.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    content_type: Mapped[ContentType] = mapped_column(
        Enum(ContentType, name="content_type"), default=ContentType.TEXT
    )

    # Пайплайн модерации: сработал ли content_filter (см. app/moderation/content_filter.py).
    is_flagged: Mapped[bool] = mapped_column(default=False)
    # Ограниченное хранение — см. app/tasks/cleanup.py и CLAUDE.md п.4 (приватность).
    is_deleted: Mapped[bool] = mapped_column(default=False)
