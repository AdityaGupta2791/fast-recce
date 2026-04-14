"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. All values loaded from environment or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "FastRecce"
    environment: str = Field(default="development", pattern="^(development|staging|production)$")
    debug: bool = False
    log_level: str = "INFO"

    # --- Database ---
    database_url: PostgresDsn
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- S3 / MinIO ---
    s3_endpoint_url: str | None = None
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "fastrecce-snapshots"
    s3_region: str = "us-east-1"

    # --- Auth ---
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # --- External APIs ---
    google_places_api_key: str
    gemini_api_key: str
    gemini_model: str = "gemini-3-flash-preview"

    # --- Rate limits ---
    google_places_rate_limit_rpm: int = 60
    crawl_concurrency: int = 5
    crawl_timeout_seconds: int = 30

    # --- Pipeline ---
    default_cities: list[str] = [
        "Mumbai",
        "Thane",
        "Navi Mumbai",
        "Lonavala",
        "Pune",
        "Alibaug",
    ]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()  # type: ignore[call-arg]
