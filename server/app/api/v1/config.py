from fastapi import APIRouter

from app.config import get_settings
from app.schemas.config import PublicConfigResponse

router = APIRouter(tags=["config"])


@router.get("/config/public", response_model=PublicConfigResponse)
async def public_config() -> PublicConfigResponse:
    """Публичная конфигурация для клиентов — сейчас только флаг/site key
    reCAPTCHA (см. app/moderation/captcha.py, task190826). Секретный ключ сюда
    никогда не попадает."""
    settings = get_settings()
    enabled = settings.recaptcha_enabled and bool(settings.recaptcha_site_key)
    return PublicConfigResponse(
        recaptcha_enabled=enabled,
        recaptcha_site_key=settings.recaptcha_site_key if enabled else None,
    )
