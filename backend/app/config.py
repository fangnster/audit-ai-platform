from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pathlib import Path

# Support .env in current dir OR parent dir (project root when running from backend/)
_env_file = ".env" if Path(".env").exists() else "../.env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_file, extra="ignore")

    # App
    APP_NAME: str = "Immigration AI Platform"
    APP_VERSION: str = "1.0.0"
    APP_TIMEZONE: str = "Asia/Shanghai"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Database (Supabase / PostgreSQL)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/immigration_db"

    # Redis (Upstash)
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 45

    # Object Storage (Cloudflare R2 / MinIO - S3 compatible)
    STORAGE_ENDPOINT_URL: str = ""          # e.g. https://<id>.r2.cloudflarestorage.com
    STORAGE_ACCESS_KEY: str = ""
    STORAGE_SECRET_KEY: str = ""
    STORAGE_BUCKET_NAME: str = "immigration-docs"
    STORAGE_PUBLIC_URL: str = ""           # CDN URL prefix
    STORAGE_REGION: str = ""               # e.g. Supabase project region, us-east-1 for many S3-compatible stores

    # LLM Providers (legacy named keys)
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    DEFAULT_LLM: str = "minimax"

    # Generic LLM provider (overrides named keys when set)
    LLM_PROVIDER: str = "minimax"          # minimax|claude|gpt4o|gemini|ollama
    LLM_API_KEY: Optional[str] = None      # unified API key
    LLM_BASE_URL: Optional[str] = None     # custom endpoint (for MiniMax / Azure / Ollama)
    LLM_MODEL: str = "MiniMax-M2.7"        # model name passed to the provider
    LLM_CACHE_ENABLED: bool = True
    LLM_CACHE_TTL_SECONDS: int = 900
    LLM_TIMEOUT_SECONDS: float = 120.0

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Email (optional - for RFI notifications)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None

    # Logging / ops
    LOG_LEVEL: str = "INFO"
    REQUEST_LOG_ENABLED: bool = True
    SQL_ECHO: bool = False


settings = Settings()
