from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "ccil.ai.platform.storage"
    host: str = "0.0.0.0"
    port: int = 8770
    log_level: str = "info"
    log_format: str = "text"

    postgres_url: str = ""
    s3_endpoint: str = "http://127.0.0.1:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "agent-executions"
    s3_region: str = "us-east-1"
    presign_expiry_seconds: int = 3600

    agent_config_base_url: str = ""
    execution_service_base_url: str = ""
    internal_api_key: str = ""
    verify_ssl: bool = True
    artifact_text_max_chars: int = 12000


@lru_cache
def get_settings() -> Settings:
    return Settings()
