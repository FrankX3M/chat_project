import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.redis_client import get_redis
from app.core.security import InvalidTokenError, TokenType, decode_token
from app.db.session import async_session_maker
from app.models.user import User, UserStatus
from app.ws.connection_manager import connection_manager
from app.ws.event_handlers import dispatch_event, handle_disconnect, parse_client_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])


@router.websocket("/ws/connect")
async def ws_connect(websocket: WebSocket, token: str = Query(...)) -> None:
    """Один сокет на пользователя обслуживает и ожидание матча, и сам чат —
    клиенту не нужно переподключаться при переходе "поиск → чат" (см.
    project-structure.md, раздел 5)."""
    try:
        user_id = decode_token(token, TokenType.ACCESS)
    except InvalidTokenError:
        await websocket.close(code=4401, reason="invalid or expired token")
        return

    async with async_session_maker() as db:
        user = await db.get(User, user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            await websocket.close(code=4403, reason="account not found or restricted")
            return

    await connection_manager.connect(user_id, websocket)
    redis = get_redis()

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                raw = json.loads(raw_text)
                event = parse_client_event(raw)
            except (json.JSONDecodeError, ValidationError) as exc:
                logger.info("bad ws payload from %s: %s", user_id, exc)
                continue

            async with async_session_maker() as db:
                user = await db.get(User, user_id)
                if user is None:
                    break
                await dispatch_event(user, event, db, redis)
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(user_id, websocket)
        asyncio.create_task(handle_disconnect(user_id))
