import secrets
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Строка-приманка из старых версий .env.example. Раньше она же была дефолтом в
# коде — т.е. любой, кто не тронул .env, реально работал с публично известным
# секретом (см. security-скан: JWT Authentication Bypass, CWE-798, CVSS 9.1).
# Теперь: (1) дефолт — случайный секрет на каждый запуск процесса, а не эта
# строка; (2) если кто-то всё же явно пропишет её в .env — приложение
# отказывается стартовать, а не работает "как ни в чём не бывало".
_KNOWN_INSECURE_PLACEHOLDER = "change-me-in-production"


def _random_secret() -> str:
    """Secure-by-default: если секрет не задан явно, а не тихо подставлен
    предсказуемый placeholder. Минус — рестарт процесса инвалидирует все
    текущие JWT (для анонимного эфемерного чата это не критично: пользователь
    просто получает новую сессию). Для стабильности сессий между рестартами
    задайте JWT_SECRET/IP_HASH_SALT явно в .env (см. .env.example)."""
    return secrets.token_hex(32)


class Settings(BaseSettings):
    """Единый источник конфигурации, читается из .env / переменных окружения."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://anon_chat:anon_chat@localhost:5432/anon_chat"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_ttl: int = 900
    jwt_refresh_ttl: int = 2592000

    # NB: как и jwt_secret, при пустом значении генерируется случайно на
    # каждый рестарт процесса (см. _resolve_secret ниже) — значит ip_hash
    # (app/core/security.py::hash_ip) для одного и того же реального IP тоже
    # будет разным после каждого рестарта. Для rate-limit-бакета это не
    # проблема (он короткоживущий), но если ip_hash когда-нибудь понадобится
    # для чего-то долгоживущего (баны, сопоставление паттернов абьюза между
    # сессиями) — здесь потребуется зафиксированное значение в .env (см. README
    # "Секреты"), иначе сопоставление перестанет работать после каждого деплоя.
    ip_hash_salt: str = ""

    room_reconnect_grace_seconds: int = 20
    match_loop_interval_seconds: float = 1.0

    search_start_rate_limit: int = 10
    search_start_rate_window_seconds: int = 60

    environment: str = "local"

    @field_validator("jwt_secret", "ip_hash_salt")
    @classmethod
    def _resolve_secret(cls, v: str, info) -> str:
        if v == _KNOWN_INSECURE_PLACEHOLDER:
            raise ValueError(
                f"{info.field_name.upper()} is set to the insecure placeholder "
                f'"{_KNOWN_INSECURE_PLACEHOLDER}" — anyone who has read the source '
                "or docs can forge tokens with it. Generate a real secret and put it "
                'in .env, e.g.: python3 -c "import secrets; print(secrets.token_hex(32))"'
            )
        if not v:
            return _random_secret()
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
