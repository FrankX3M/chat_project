import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.chat import room_manager
from app.chat.message_service import get_history
from app.db.session import get_db
from app.models.chat_room import EndReason
from app.models.user import User
from app.schemas.chat import MessageHistoryResponse, MessageOut
from app.schemas.ws_events import PartnerLeftEvent, PartnerLeftPayload
from app.ws.connection_manager import connection_manager

router = APIRouter(tags=["rooms"])


async def _get_room_for_participant(db: AsyncSession, room_id: uuid.UUID, user: User):
    room = await room_manager.get_room(db, room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="room not found")
    if not room_manager.is_participant(room, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a room participant")
    return room


@router.get("/rooms/{room_id}/messages", response_model=MessageHistoryResponse)
async def get_room_messages(
    room_id: uuid.UUID,
    cursor: uuid.UUID | None = Query(default=None, description="id последнего полученного сообщения"),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageHistoryResponse:
    await _get_room_for_participant(db, room_id, user)
    messages = await get_history(db, room_id=room_id, before=cursor, limit=limit)
    items = [MessageOut.model_validate(m) for m in messages]
    next_cursor = str(items[0].id) if len(items) == limit else None
    return MessageHistoryResponse(items=items, next_cursor=next_cursor)


@router.post("/rooms/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_room(
    room_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Покинуть комнату через REST — дублирует WS-событие `leave` для клиентов
    без активного сокета (см. project-structure.md, раздел 4).

    Партнёра всё равно нужно уведомить по WS, если он сейчас на связи —
    иначе он узнает о закрытии комнаты только когда его следующее
    сообщение/typing вернётся с ошибкой `room_not_found` (см. код-ревью)."""
    room = await _get_room_for_participant(db, room_id, user)
    partner_id = room_manager.other_participant(room, user.id)
    await room_manager.end_room(db, room, reason=EndReason.USER_LEFT)
    await connection_manager.send_event(
        partner_id,
        PartnerLeftEvent(payload=PartnerLeftPayload(room_id=room.id, reason=EndReason.USER_LEFT.value)),
    )
