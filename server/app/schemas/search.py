import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.user import Gender


class SearchStartRequest(BaseModel):
    topic: str | None = Field(default=None, max_length=64)
    partner_gender: Gender = Gender.UNSPECIFIED
    partner_age_min: int | None = Field(default=None, ge=13, le=120)
    partner_age_max: int | None = Field(default=None, ge=13, le=120)


class SearchStatusValue(StrEnum):
    IDLE = "idle"
    SEARCHING = "searching"
    MATCHED = "matched"


class SearchStatusResponse(BaseModel):
    status: SearchStatusValue
    room_id: uuid.UUID | None = None
    queue_position: int | None = None
