import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ChatRoomStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


class EndReason(StrEnum):
    USER_LEFT = "user_left"
    BOTH_LEFT = "both_left"
    REPORTED = "reported"
    TIMEOUT = "timeout"
    BANNED = "banned"


class ChatRoom(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "chat_rooms"

    user1_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user2_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    topic: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[ChatRoomStatus] = mapped_column(
        Enum(ChatRoomStatus, name="chat_room_status"), default=ChatRoomStatus.ACTIVE
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[EndReason | None] = mapped_column(
        Enum(EndReason, name="end_reason"), nullable=True
    )
