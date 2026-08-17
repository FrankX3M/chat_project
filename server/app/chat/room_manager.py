import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models.chat_room import ChatRoom, ChatRoomStatus, EndReason


async def create_room(
    db: AsyncSession, *, user1_id: uuid.UUID, user2_id: uuid.UUID, topic: str | None
) -> ChatRoom:
    room = ChatRoom(
        user1_id=user1_id,
        user2_id=user2_id,
        topic=topic,
        status=ChatRoomStatus.ACTIVE,
        started_at=utcnow(),
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


async def get_room(db: AsyncSession, room_id: uuid.UUID) -> ChatRoom | None:
    return await db.get(ChatRoom, room_id)


async def get_active_room_for_user(db: AsyncSession, user_id: uuid.UUID) -> ChatRoom | None:
    stmt = select(ChatRoom).where(
        ChatRoom.status == ChatRoomStatus.ACTIVE,
        (ChatRoom.user1_id == user_id) | (ChatRoom.user2_id == user_id),
    )
    result = await db.execute(stmt)
    return result.scalars().first()


def other_participant(room: ChatRoom, user_id: uuid.UUID) -> uuid.UUID:
    return room.user2_id if room.user1_id == user_id else room.user1_id


def is_participant(room: ChatRoom, user_id: uuid.UUID) -> bool:
    return user_id in (room.user1_id, room.user2_id)


async def end_room(
    db: AsyncSession, room: ChatRoom, *, reason: EndReason
) -> ChatRoom:
    if room.status == ChatRoomStatus.ENDED:
        return room
    room.status = ChatRoomStatus.ENDED
    room.ended_at = utcnow()
    room.end_reason = reason
    await db.commit()
    await db.refresh(room)
    return room
