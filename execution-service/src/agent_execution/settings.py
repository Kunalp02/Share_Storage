from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "ccil.ai.platform.agent_execution"
    host: str = "0.0.0.0"
    port: int = 8765
    log_level: str = "info"
    cors_origins: str = "http://localhost:3000"

    agent_config_base_url: str = ""
    tools_config_base_url: str = ""
    rag_config_base_url: str = ""
    rag_ask_base_url: str = ""
    auth_service_base_url: str = ""
    auth_service_username: str = ""
    auth_service_password: str = ""
    auth_token_refresh_margin_seconds: int = 60

    bifrost_gateway_base_url: str = ""
    bifrost_gateway_api_key: str = ""
    llm_gateway_mock: bool = False
    llm_chat_completions_path: str = "/v1/chat/completions"
    llm_gateway_timeout_seconds: float = 120.0
    verify_ssl: bool = True

    manifest_cache_ttl_seconds: int = 120
    model_cache_ttl_seconds: int = 300
    memory_cache_ttl_seconds: int = 30
    skip_model_registry_lookup: bool = True
    use_runtime_manifest_endpoint: bool = True
    persist_conversation_memory: bool = True
    conversation_max_turn_pairs: int = 10
    conversation_max_chars: int = 8000
    max_tool_rounds: int = 5

    execution_database_url: str = ""
    conversation_store_database_url: str = ""

    storage_service_base_url: str = ""
    storage_internal_api_key: str = ""

    test_thread_ttl_hours: int = 24
    default_production_retention_policy: str = "PERMANENT"
    cleanup_interval_seconds: int = 300

    max_inflight_runs: int = 8
    run_slot_wait_seconds: float = 2.0
    run_lease_seconds: int = 180
    run_max_attempts: int = 3
    worker_poll_seconds: float = 1.0
    worker_id: str = ""
    artifact_prompt_max_chars: int = 12000
    persist_output_artifacts: bool = True

    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def database_url(self) -> str:
        return self.execution_database_url or self.conversation_store_database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
