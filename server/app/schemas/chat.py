import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.message import ContentType


class MessageOut(BaseModel):
    id: uuid.UUID
    room_id: uuid.UUID
    sender_id: uuid.UUID
    content: str
    content_type: ContentType
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageHistoryResponse(BaseModel):
    items: list[MessageOut]
    next_cursor: str | None = None
