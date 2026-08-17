from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    InvalidTokenError,
    TokenType,
    create_access_token,
    create_token_pair,
    decode_token,
    hash_ip,
)
from app.db.base import utcnow
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    AnonymousAuthRequest,
    RefreshRequest,
    TokenPairResponse,
)

router = APIRouter(tags=["auth"])


@router.post("/auth/anonymous", response_model=TokenPairResponse)
async def anonymous_auth(
    body: AnonymousAuthRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenPairResponse:
    """Создать/восстановить анонимного пользователя по device_id, выдать JWT-пару.

    NB: проверка `bans` по ip_hash/device_fingerprint_hash — часть модуля
    модерации (см. project-structure.md 6.1), в MVP-срезе не подключена.
    """
    result = await db.execute(select(User).where(User.device_id == body.device_id))
    user = result.scalars().first()

    client_ip = request.client.host if request.client else None
    ip_hash = hash_ip(client_ip)

    if user is None:
        user = User(device_id=body.device_id, ip_hash=ip_hash, last_seen_at=utcnow())
        db.add(user)
    else:
        user.ip_hash = ip_hash
        user.last_seen_at = utcnow()

    await db.commit()
    await db.refresh(user)

    access_token, refresh_token = create_token_pair(user.id)
    return TokenPairResponse(
        user_id=user.id, access_token=access_token, refresh_token=refresh_token
    )


@router.post("/auth/refresh", response_model=AccessTokenResponse)
async def refresh_token(
    body: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> AccessTokenResponse:
    try:
        user_id = decode_token(body.refresh_token, TokenType.REFRESH)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired refresh token"
        ) from exc

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")

    return AccessTokenResponse(access_token=create_access_token(user.id))
