import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def _create_token(user_id: uuid.UUID, token_type: TokenType, ttl_seconds: int) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": token_type.value,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID) -> str:
    return _create_token(user_id, TokenType.ACCESS, settings.jwt_access_ttl)


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _create_token(user_id, TokenType.REFRESH, settings.jwt_refresh_ttl)


def create_token_pair(user_id: uuid.UUID) -> tuple[str, str]:
    return create_access_token(user_id), create_refresh_token(user_id)


class InvalidTokenError(Exception):
    pass


def decode_token(token: str, expected_type: TokenType) -> uuid.UUID:
    """Валидирует подпись/срок действия/тип токена, возвращает user_id."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidTokenError("token invalid or expired") from exc

    if payload.get("type") != expected_type.value:
        raise InvalidTokenError("unexpected token type")

    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("token missing subject") from exc


def hash_ip(ip: str | None) -> str | None:
    """Хэш IP с солью — сырой IP никогда не хранится (см. CLAUDE.md, приватность по умолчанию)."""
    if not ip:
        return None
    digest = hashlib.sha256(f"{settings.ip_hash_salt}:{ip}".encode()).hexdigest()
    return digest
