from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.user_settings import UserSettings
from app.schemas.settings import UserSettingsResponse, UserSettingsUpdate

router = APIRouter(tags=["settings"])

MIN_ADULT_AGE = 18


async def _get_or_create_settings(db: AsyncSession, user_id) -> UserSettings:
    existing = await db.get(UserSettings, user_id)
    if existing is not None:
        return existing
    created = UserSettings(user_id=user_id)
    db.add(created)
    await db.commit()
    await db.refresh(created)
    return created


def _to_response(user: User, settings_row: UserSettings) -> UserSettingsResponse:
    return UserSettingsResponse(
        gender=user.gender,
        age=user.age,
        is_age_verified=user.is_age_verified,
        preferred_topic=settings_row.preferred_topic,
        preferred_partner_gender=settings_row.preferred_partner_gender,
        preferred_age_min=settings_row.preferred_age_min,
        preferred_age_max=settings_row.preferred_age_max,
        color_theme=settings_row.color_theme,
        is_18_plus_mode=settings_row.is_18_plus_mode,
    )


@router.get("/settings", response_model=UserSettingsResponse)
async def get_settings_endpoint(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UserSettingsResponse:
    settings_row = await _get_or_create_settings(db, user.id)
    return _to_response(user, settings_row)


@router.put("/settings", response_model=UserSettingsResponse)
async def update_settings_endpoint(
    body: UserSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSettingsResponse:
    settings_row = await _get_or_create_settings(db, user.id)

    # Собственный профиль — хранится на users, не на user_settings.
    user.gender = body.gender
    user.age = body.age

    # Самодекларация возраста (method=self_declaration, см. project-structure.md 3.8):
    # если пользователь явно подтвердил "мне есть 18" и указал возраст >= 18 —
    # засчитываем верификацию. Полноценная KYC-интеграция — отдельная задача, вне MVP.
    if body.self_declared_adult and body.age is not None and body.age >= MIN_ADULT_AGE:
        user.is_age_verified = True

    # Требует is_age_verified=true — не ослаблять эту проверку (см. CLAUDE.md п.6).
    # Это чувствительная зона продукта: раньше тихо сбрасывали флаг, теперь явно
    # отказываем с понятной ошибкой, чтобы фронтенд мог показать причину.
    if body.is_18_plus_mode and not user.is_age_verified:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="18+ topic requires self_declared_adult=true and age>=18",
        )

    settings_row.preferred_topic = body.preferred_topic
    settings_row.preferred_partner_gender = body.preferred_partner_gender
    settings_row.preferred_age_min = body.preferred_age_min
    settings_row.preferred_age_max = body.preferred_age_max
    settings_row.color_theme = body.color_theme
    settings_row.is_18_plus_mode = body.is_18_plus_mode

    await db.commit()
    await db.refresh(user)
    await db.refresh(settings_row)
    return _to_response(user, settings_row)
