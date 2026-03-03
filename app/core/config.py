from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import EmailStr, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─────────────────────────────────────────────
    # App
    # ─────────────────────────────────────────────
    APP_NAME: str = "Mobily Tech Support System"
    APP_VERSION: str = "4.1.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    SECRET_KEY: str = Field(..., min_length=32)
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]
    CORS_ORIGINS: list[str] = ["http://localhost:8000", "http://localhost:3000"]
    BASE_URL: str = "http://localhost:8000"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            if v.startswith("["):
                import json
                return json.loads(v)
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # ─────────────────────────────────────────────
    # Database (PostgreSQL 16.4)
    # ─────────────────────────────────────────────
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "mobily_support"
    POSTGRES_USER: str = "mobily"
    POSTGRES_PASSWORD: str = Field(..., min_length=8, description="DB password — must set in .env")

    # Connection pool settings
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Sync URL for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ─────────────────────────────────────────────
    # Redis 7.2
    # ─────────────────────────────────────────────
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = Field(..., min_length=8, description="Redis password — must set in .env")
    REDIS_DB: int = 0

    # TTLs (seconds)
    REDIS_TTL_SESSION: int = 86400       # 24 hours
    REDIS_TTL_PERMISSIONS: int = 900     # 15 minutes
    REDIS_TTL_KPI_CACHE: int = 300       # 5 minutes
    REDIS_TTL_RATE_LIMIT: int = 60       # 1 minute

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ─────────────────────────────────────────────
    # Celery
    # ─────────────────────────────────────────────
    CELERY_BROKER_URL: str = ""          # auto-set from REDIS_URL if empty
    CELERY_RESULT_BACKEND: str = ""      # auto-set from REDIS_URL if empty

    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

    # ─────────────────────────────────────────────
    # JWT / Auth
    # Dev:  JWT_ALGORITHM=HS256, set JWT_PRIVATE_KEY=JWT_PUBLIC_KEY=SECRET_KEY
    # Prod: JWT_ALGORITHM=RS256, provide real RSA-4096 PEM strings
    # ─────────────────────────────────────────────
    JWT_PRIVATE_KEY: str = Field(default="", description="RSA private key PEM (leave blank for HS256 dev mode)")
    JWT_PUBLIC_KEY: str = Field(default="", description="RSA public key PEM (leave blank for HS256 dev mode)")
    JWT_ALGORITHM: str = "HS256"

    @property
    def jwt_sign_key(self) -> str:
        """Key used to sign tokens. RSA private key for RS256, SECRET_KEY for HS256."""
        return self.JWT_PRIVATE_KEY or self.SECRET_KEY

    @property
    def jwt_verify_key(self) -> str:
        """Key used to verify tokens. RSA public key for RS256, SECRET_KEY for HS256."""
        return self.JWT_PUBLIC_KEY or self.SECRET_KEY
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60   # 1 hour (was 24h — security hardening)
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Argon2id password hashing params
    ARGON2_TIME_COST: int = 3
    ARGON2_MEMORY_COST: int = 65536     # 64 MB
    ARGON2_PARALLELISM: int = 4

    # ─────────────────────────────────────────────
    # File Storage (S3-compatible: Backblaze B2 / MinIO)
    # ─────────────────────────────────────────────
    S3_ENDPOINT_URL: str = ""           # e.g. https://s3.us-west-004.backblazeb2.com
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET_NAME: str = "mobily-support"
    S3_REGION: str = "us-east-1"
    S3_SIGNED_URL_EXPIRY: int = 3600    # 1 hour

    # File Upload Limits
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024   # 10 MB
    ALLOWED_MIME_TYPES: list[str] = [
        "image/jpeg",
        "image/png",
        "image/gif",
        "application/pdf",
        "application/zip",
        "text/plain",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]

    # ─────────────────────────────────────────────
    # Email (SMTP outbound + IMAP inbound)
    # ─────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True
    SMTP_FROM_EMAIL: EmailStr = "support@mobily.com.sa"
    SMTP_FROM_NAME: str = "Mobily Support"

    IMAP_HOST: str = "imap.gmail.com"
    IMAP_PORT: int = 993
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""
    IMAP_FOLDER: str = "INBOX"
    IMAP_POLL_INTERVAL_SECONDS: int = 60

    # ─────────────────────────────────────────────
    # Twilio (SMS + WhatsApp)
    # ─────────────────────────────────────────────
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_SMS_FROM: str = ""           # e.g. +966xxxxxxxxx
    TWILIO_WHATSAPP_FROM: str = ""      # e.g. whatsapp:+14155238886

    # ─────────────────────────────────────────────
    # ClamAV Virus Scanner
    # ─────────────────────────────────────────────
    CLAMD_HOST: str = "localhost"
    CLAMD_PORT: int = 3310
    CLAMAV_ENABLED: bool = True

    # ─────────────────────────────────────────────
    # Sentry (Error Monitoring)
    # ─────────────────────────────────────────────
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.1, ge=0.0, le=1.0)
    SENTRY_PROFILES_SAMPLE_RATE: float = Field(default=0.1, ge=0.0, le=1.0)

    # ─────────────────────────────────────────────
    # Internationalization
    # ─────────────────────────────────────────────
    DEFAULT_LANGUAGE: Literal["ar", "en"] = "ar"
    SUPPORTED_LANGUAGES: list[str] = ["ar", "en"]
    TIMEZONE: str = "Asia/Riyadh"

    # ─────────────────────────────────────────────
    # SLA Business Hours
    # ─────────────────────────────────────────────
    BUSINESS_HOURS_START: int = 8        # 08:00
    BUSINESS_HOURS_END: int = 16         # 16:00
    BUSINESS_DAYS: list[int] = [6, 0, 1, 2, 3]  # Sun=6, Mon=0, Tue=1, Wed=2, Thu=3

    # ─────────────────────────────────────────────
    # Rate Limiting
    # ─────────────────────────────────────────────
    RATE_LIMIT_PORTAL: str = "20/minute"
    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_REGISTER: str = "3/hour"
    RATE_LIMIT_API: str = "100/minute"

    # ─────────────────────────────────────────────
    # CSAT
    # ─────────────────────────────────────────────
    CSAT_TOKEN_EXPIRY_DAYS: int = 7

    # ─────────────────────────────────────────────
    # Ticket Number
    # ─────────────────────────────────────────────
    TICKET_NUMBER_PREFIX: str = "TKT"

    # ─────────────────────────────────────────────
    # Flower (Celery monitoring)
    # ─────────────────────────────────────────────
    FLOWER_USER: str = Field(default="admin", description="Flower monitoring user")
    FLOWER_PASSWORD: str = Field(..., min_length=8, description="Flower password — must set in .env")

    # ─────────────────────────────────────────────
    # Encryption (for integration_configs values)
    # ─────────────────────────────────────────────
    FIELD_ENCRYPTION_KEY: str = Field(
        ...,
        description="Fernet or AES-256 key for encrypting sensitive DB fields",
    )

    # ── Computed aliases for services that use AWS_ prefix ─────────────────
    IMAP_SSL: bool = True

    @property
    def AWS_ACCESS_KEY_ID(self) -> str:
        return self.S3_ACCESS_KEY_ID

    @property
    def AWS_SECRET_ACCESS_KEY(self) -> str:
        return self.S3_SECRET_ACCESS_KEY

    @property
    def AWS_REGION(self) -> str:
        return self.S3_REGION

    @property
    def AWS_ENDPOINT_URL(self) -> str:
        return self.S3_ENDPOINT_URL

    @property
    def S3_BUCKET(self) -> str:
        return self.S3_BUCKET_NAME

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
