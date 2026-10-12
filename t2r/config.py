"""Settings loaded from environment variables (design doc 16.3). Secrets never live in code."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://app:app@localhost:5432/t2r"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "t2r"
    minio_secure: bool = False

    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    claude_small_model: str = "claude-haiku-5-5"

    embeddings_provider: str = "local"
    embedding_dim: int = 1024

    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_access_token: str = ""

    feed_poll_seconds: int = 300
    event_feed_poll_seconds: int = 1800
    download_rate_per_second: float = 1.0
    user_agent: str = "Ticker-to-Report/0.1"
    http_timeout_seconds: float = 30.0

    import_dir: Path = Path("./import")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    smtp_url: str = ""
    alert_email_to: str = ""

    excel_bridge_url: str = "http://localhost:8765"
    api_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
