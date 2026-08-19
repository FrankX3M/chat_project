from pydantic import BaseModel


class PublicConfigResponse(BaseModel):
    """Публичная (без авторизации) конфигурация для клиентов — только то, что
    не является секретом (см. task190826: клиенту нужен site key reCAPTCHA,
    а не секретный ключ, который остаётся на сервере)."""

    recaptcha_enabled: bool = False
    recaptcha_site_key: str | None = None
