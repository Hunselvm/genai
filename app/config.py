"""Application configuration using Pydantic Settings."""

from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Configuration
    veo_api_key: str
    veo_base_url: str = "https://genaipro.vn/api/v1"
    veo_ws_url: str = "wss://genaipro.vn/ws"

    # Application Settings
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    debug: bool = False

    # File Settings
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 50
    allowed_image_formats: List[str] = ["jpg", "jpeg", "png", "webp"]

    # Batch Processing
    max_concurrent_jobs: int = 1
    batch_db_path: str = "data/batch_queue.db"

    # Rate Limiting
    requests_per_minute: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore"
    )


# Global settings instance
settings = Settings()
