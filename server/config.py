from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./skype_reborn.db"
    SECRET_KEY: str  # Must be set via SECRET_KEY env var or .env file
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    UPLOAD_DIR: str = "server/uploads"
    MAX_UPLOAD_BYTES: int = 100 * 1024 * 1024  # 100 MB
    # Restrict CORS to known origins. Override via CORS_ORIGINS env var (JSON list).
    CORS_ORIGINS: List[str] = ["http://127.0.0.1:8080", "http://localhost:8080"]

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
