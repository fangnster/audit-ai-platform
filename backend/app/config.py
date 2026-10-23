from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pathlib import Path

# Support .env in current dir OR parent dir (project root when running from backend/)
_env_file = ".env" if Path(".env").exists() else "../.env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_file, extra="ignore")

    # App
    APP_NAME: str = "Audit AI Platform"
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
    ADMIN_CACHE_TTL_SECONDS: int = 15

    # Object Storage (Cloudflare R2 / MinIO - S3 compatible)
    STORAGE_ENDPOINT_URL: str = ""          # e.g. https://<id>.r2.cloudflarestorage.com
    STORAGE_ACCESS_KEY: str = ""
    STORAGE_SECRET_KEY: str = ""
    STORAGE_BUCKET_NAME: str = "immigration-docs"
    STORAGE_PUBLIC_URL: str = ""           # CDN URL prefix
    STORAGE_REGION: str = ""               # e.g. Supabase project region, us-east-1 for many S3-compatible stores
    DOCUMENT_DB_FALLBACK_MAX_BYTES: int = 25 * 1024 * 1024

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

    # Draft generation budgets. Remote LLM endpoints are much more reliable when
    # each job has a bounded prompt and output size.
    DRAFT_MAX_FACTS: int = 24
    DRAFT_MAX_FACT_CHARS: int = 700
    DRAFT_MAX_FACT_QUOTE_CHARS: int = 260
    DRAFT_MAX_KNOWLEDGE_ITEMS: int = 4
    DRAFT_MAX_KNOWLEDGE_CHARS: int = 1200
    DRAFT_MAX_USER_PROMPT_CHARS: int = 2500
    DRAFT_GENERATION_MAX_TOKENS: int = 2400
    DRAFT_CUSTOM_MAX_TOKENS: int = 1800
    DRAFT_REWRITE_MAX_TOKENS: int = 1800
    DRAFT_TASK_SOFT_TIME_LIMIT_SECONDS: int = 420
    DRAFT_TASK_TIME_LIMIT_SECONDS: int = 480

    # Document parsing budgets.
    PARSE_MAX_CONTENT_CHARS: int = 8500
    PARSE_MAX_LAWYER_GUIDANCE_CHARS: int = 1800
    PARSE_MAX_FACTS: int = 18
    PARSE_MAX_OUTPUT_TOKENS: int = 1800
    PARSE_MIN_READABLE_TEXT_CHARS: int = 10
    PARSE_RESUME_MAX_FACTS: int = 32
    PARSE_RESUME_MAX_OUTPUT_TOKENS: int = 2800
    PARSE_CHUNK_MAX_CHARS: int = 5200
    PARSE_CHUNK_OVERLAP_CHARS: int = 450
    PARSE_MAX_CHUNKS: int = 5
    PARSE_PDF_OCR_MAX_PAGES: int = 8
    PARSE_PDF_OCR_DPI: int = 180
    PARSE_TASK_SOFT_TIME_LIMIT_SECONDS: int = 900
    PARSE_TASK_TIME_LIMIT_SECONDS: int = 960

    # Agent task watchdog. If a worker is killed or a broker delivery is lost,
    # queued/processing records can otherwise keep UI actions locked forever.
    AGENT_TASK_QUEUED_TIMEOUT_MINUTES: int = 10
    AGENT_TASK_PROCESSING_TIMEOUT_MINUTES: int = 18

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
    SYSTEM_ADMIN_EMAILS: str = ""


settings = Settings()
