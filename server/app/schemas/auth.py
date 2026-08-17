import uuid

from pydantic import BaseModel, Field


class AnonymousAuthRequest(BaseModel):
    device_id: str = Field(min_length=8, max_length=128)


class TokenPairResponse(BaseModel):
    user_id: uuid.UUID
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
