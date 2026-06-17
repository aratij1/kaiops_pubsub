from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = Field(default="kaiops-service", alias="SERVICE_NAME")
    environment: str = Field(default="local", alias="ENVIRONMENT")
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_group_id: str = Field(default="kaiops", alias="KAFKA_GROUP_ID")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    database_url: str = Field(
        default="postgresql+asyncpg://kaiops:kaiops@localhost:5432/kaiops",
        alias="DATABASE_URL",
    )
    otlp_endpoint: str | None = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    model_router_url: str = Field(default="http://model-router:8000", alias="MODEL_ROUTER_URL")
    context_agent_url: str = Field(default="http://context-agent:8000", alias="CONTEXT_AGENT_URL")
    approval_service_url: str = Field(
        default="http://approval-service:8000", alias="APPROVAL_SERVICE_URL"
    )
    kafka_enabled: bool = Field(default=True, alias="KAFKA_ENABLED")
    database_enabled: bool = Field(default=True, alias="DATABASE_ENABLED")
    local_llm_endpoint: str = Field(default="http://ollama:11434", alias="LOCAL_LLM_ENDPOINT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
