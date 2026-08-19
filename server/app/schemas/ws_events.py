"""Единый источник правды для WS-контракта.

Любое новое событие или изменение payload сначала добавляется сюда, потом
реализуется в app/ws/event_handlers.py, потом синхронизируется shared/ws-events.md
(см. CLAUDE.md п.2). Рассинхрон между схемой и документом недопустим.
"""

import uuid
from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from app.models.message import ContentType
from app.models.user import Gender, PlotRole
from app.schemas.search import AgeRange


class ClientEventType(StrEnum):
    JOIN_QUEUE = "join_queue"
    CANCEL_QUEUE = "cancel_queue"
    MESSAGE = "message"
    TYPING = "typing"
    LEAVE = "leave"


class ServerEventType(StrEnum):
    MATCHED = "matched"
    MESSAGE = "message"
    TYPING = "typing"
    PARTNER_LEFT = "partner_left"
    QUEUE_POSITION = "queue_position"
    ERROR = "error"


# ---- клиент → сервер ----------------------------------------------------


class JoinQueuePayload(BaseModel):
    topic: str | None = Field(default=None, max_length=64)
    partner_gender: Gender = Gender.UNSPECIFIED
    # Те же границы, что и в schemas/search.py::SearchStartRequest — это два
    # независимых входа в одну очередь, расхождение в валидации раньше
    # позволяло через WS прислать, например, partner_age_min=-500 (см. код-ревью).
    partner_age_min: int | None = Field(default=None, ge=13, le=120)
    partner_age_max: int | None = Field(default=None, ge=13, le=120)
    # task190826_v2: тот же множественный выбор диапазонов возраста
    # собеседника, что и в SearchStartRequest.partner_age_ranges — WS
    # join_queue дублирует REST /search/start как альтернативная точка входа,
    # оба должны принимать одинаковый payload (см. CLAUDE.md п.2).
    partner_age_ranges: list[AgeRange] = Field(default_factory=list)
    # task190826: тот же критерий, что и в SearchStartRequest.plot_role — WS
    # join_queue дублирует REST /search/start как альтернативная точка входа.
    plot_role: PlotRole | None = None


class JoinQueueEvent(BaseModel):
    event: Literal[ClientEventType.JOIN_QUEUE] = ClientEventType.JOIN_QUEUE
    payload: JoinQueuePayload = JoinQueuePayload()


class CancelQueueEvent(BaseModel):
    event: Literal[ClientEventType.CANCEL_QUEUE] = ClientEventType.CANCEL_QUEUE
    payload: dict = {}


class ClientMessagePayload(BaseModel):
    room_id: uuid.UUID
    content: str = Field(min_length=1, max_length=4000)
    content_type: ContentType = ContentType.TEXT
    # task190826: простая антиспам-капча для первых N сообщений пользователя
    # (см. app/moderation/captcha.py). Не обязателен — валидность/нужность
    # проверяется на сервере (settings.recaptcha_enabled), клиент присылает
    # его только когда получил ошибку `captcha_required` и решил виджет.
    captcha_token: str | None = Field(default=None, max_length=4000)


class ClientMessageEvent(BaseModel):
    event: Literal[ClientEventType.MESSAGE] = ClientEventType.MESSAGE
    payload: ClientMessagePayload


class TypingPayload(BaseModel):
    room_id: uuid.UUID
    is_typing: bool


class TypingEvent(BaseModel):
    event: Literal[ClientEventType.TYPING] = ClientEventType.TYPING
    payload: TypingPayload


class LeavePayload(BaseModel):
    room_id: uuid.UUID


class LeaveEvent(BaseModel):
    event: Literal[ClientEventType.LEAVE] = ClientEventType.LEAVE
    payload: LeavePayload


ClientEvent = Annotated[
    Union[JoinQueueEvent, CancelQueueEvent, ClientMessageEvent, TypingEvent, LeaveEvent],
    Field(discriminator="event"),
]


# ---- сервер → клиент ------------------------------------------------------


class PartnerInfo(BaseModel):
    gender: Gender
    age_range: str | None = None
    topic: str | None = None


class MatchedPayload(BaseModel):
    room_id: uuid.UUID
    partner: PartnerInfo


class MatchedEvent(BaseModel):
    event: Literal[ServerEventType.MATCHED] = ServerEventType.MATCHED
    payload: MatchedPayload


class ServerMessagePayload(BaseModel):
    room_id: uuid.UUID
    sender: Literal["partner"] = "partner"
    content: str
    created_at: str


class ServerMessageEvent(BaseModel):
    event: Literal[ServerEventType.MESSAGE] = ServerEventType.MESSAGE
    payload: ServerMessagePayload


class ServerTypingPayload(BaseModel):
    room_id: uuid.UUID
    is_typing: bool


class ServerTypingEvent(BaseModel):
    event: Literal[ServerEventType.TYPING] = ServerEventType.TYPING
    payload: ServerTypingPayload


class PartnerLeftPayload(BaseModel):
    room_id: uuid.UUID
    reason: str


class PartnerLeftEvent(BaseModel):
    event: Literal[ServerEventType.PARTNER_LEFT] = ServerEventType.PARTNER_LEFT
    payload: PartnerLeftPayload


class QueuePositionPayload(BaseModel):
    position: int
    estimated_wait: int | None = None


class QueuePositionEvent(BaseModel):
    event: Literal[ServerEventType.QUEUE_POSITION] = ServerEventType.QUEUE_POSITION
    payload: QueuePositionPayload


class ErrorPayload(BaseModel):
    code: str
    message: str


class ErrorEvent(BaseModel):
    event: Literal[ServerEventType.ERROR] = ServerEventType.ERROR
    payload: ErrorPayload
