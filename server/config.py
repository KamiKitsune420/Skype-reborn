from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./skype_reborn.db"
    SECRET_KEY: str = "supersecretkey" # In production, use a strong secret
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    UPLOAD_DIR: str = "server/uploads"
    
    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
