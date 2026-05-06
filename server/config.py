import secrets
from typing import List, Optional

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger()


def _dev_secret_key() -> str:
    return secrets.token_urlsafe(48)


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./skype_reborn.db"
    SECRET_KEY: Optional[str] = Field(default_factory=_dev_secret_key)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    VOICE_RELAY_HOST: str = "0.0.0.0"
    VOICE_RELAY_PORT: int = 9000
    UPLOAD_DIR: str = "server/uploads"
    MAX_UPLOAD_BYTES: int = 100 * 1024 * 1024  # 100 MB
    # Restrict CORS to known origins. Override via CORS_ORIGINS env var (JSON list).
    CORS_ORIGINS: List[str] = ["http://127.0.0.1:8080", "http://localhost:8080"]

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()

if not settings.SECRET_KEY:
    raise RuntimeError("SECRET_KEY must not be empty")

if "SECRET_KEY" not in settings.model_fields_set:
    logger.warning(
        "SECRET_KEY is not set; using a temporary development key. "
        "Existing login tokens will be invalid after restart. Set SECRET_KEY in .env for stable tokens."
    )
