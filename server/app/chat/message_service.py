import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import ContentType, Message
from app.moderation.content_filter import check_message


class MessageRejected(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


async def send_message(
    db: AsyncSession,
    *,
    room_id: uuid.UUID,
    sender_id: uuid.UUID,
    content: str,
    content_type: ContentType = ContentType.TEXT,
) -> Message:
    """Единственный путь записи сообщения — всегда через content_filter (см. CLAUDE.md п.5).

    Не добавлять альтернативные точки сохранения сообщений в обход этой функции.
    """
    filter_result = await check_message(content)
    if not filter_result.is_allowed:
        raise MessageRejected(filter_result.reason or "content rejected")

    message = Message(
        room_id=room_id,
        sender_id=sender_id,
        content=content,
        content_type=content_type,
        is_flagged=filter_result.is_flagged,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def get_history(
    db: AsyncSession, *, room_id: uuid.UUID, before: uuid.UUID | None, limit: int = 50
) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.room_id == room_id, Message.is_deleted.is_(False))
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    if before is not None:
        before_msg = await db.get(Message, before)
        if before_msg is not None:
            stmt = stmt.where(Message.created_at < before_msg.created_at)

    result = await db.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()
    return messages
