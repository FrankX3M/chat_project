"""Хранение активных WS-соединений на этом инстансе + рассылка событий.

MVP — один процесс, поэтому маппинг user_id → WebSocket живёт в памяти.
При горизонтальном масштабировании (несколько инстансов сервера) сюда
подключается Redis Pub/Sub и `ws:conn:{user_id}` → id инстанса, как описано
в project-structure.md (раздел 7) — интерфейс класса рассчитан на такую замену
без переписывания вызывающего кода (event_handlers.py).
"""

import uuid

from fastapi import WebSocket
from pydantic import BaseModel


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, WebSocket] = {}

    async def connect(self, user_id: uuid.UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        # Новое подключение того же пользователя вытесняет старое (один активный сокет).
        old = self._connections.get(user_id)
        if old is not None and old is not websocket:
            await old.close(code=4000, reason="replaced by new connection")
        self._connections[user_id] = websocket

    def disconnect(self, user_id: uuid.UUID, websocket: WebSocket) -> None:
        if self._connections.get(user_id) is websocket:
            del self._connections[user_id]

    def is_online(self, user_id: uuid.UUID) -> bool:
        return user_id in self._connections

    def online_count(self) -> int:
        return len(self._connections)

    async def send_event(self, user_id: uuid.UUID, event: BaseModel) -> bool:
        """Отправляет событие пользователю, если он сейчас подключён. Возвращает успех."""
        ws = self._connections.get(user_id)
        if ws is None:
            return False
        try:
            await ws.send_text(event.model_dump_json())
            return True
        except Exception:
            self.disconnect(user_id, ws)
            return False


connection_manager = ConnectionManager()
