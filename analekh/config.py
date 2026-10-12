"""Settings from environment variables (design doc 22.3). Secrets never live in code."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://app:app@localhost:5432/analekh"
    redis_url: str = "redis://localhost:6379/0"

    # S3 API: MinIO locally, any S3 service when hosted (Appendix G.9).
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "analekh"
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
    universe_refresh_cron: str = "0 6 * * 1"  # weekly, Monday 06:00 IST
    backfill_priority: str = "NIFTY500"
    download_rate_per_second: float = 1.0
    user_agent: str = "Analekh/0.1"
    http_timeout_seconds: float = 30.0

    import_dir: Path = Path("./import")
    # Single-user until auth lands; watchlist rows are keyed by this id.
    default_user_id: str = "local"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    smtp_url: str = ""
    alert_email_to: str = ""

    # Excel bridge (runs on the analyst's machine)
    analekh_api: str = "http://localhost:8000"
    watch_folders: str = "~/Models"
    save_mode: str = "versioned"  # versioned | in_place (with automatic backup)
    excel_bridge_port: int = 8765

    @property
    def watch_folder_paths(self) -> list[Path]:
        return [Path(p).expanduser() for p in self.watch_folders.split(";") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
