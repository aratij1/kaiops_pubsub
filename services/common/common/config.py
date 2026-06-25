from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, model_validator
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
    db: str = Field(default="postgres", alias="DB")
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_user: str = Field(default="kaiops", alias="DB_USER")
    db_password: str = Field(default="kaiops", alias="DB_PASSWORD")
    db_database: str = Field(default="kaiops", alias="DB_DATABASE")
    otlp_endpoint: str | None = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    model_router_url: str = Field(default="http://model-router:8000", alias="MODEL_ROUTER_URL")
    context_agent_url: str = Field(default="http://context-agent:8000", alias="CONTEXT_AGENT_URL")
    approval_service_url: str = Field(default="http://approval-service:8000", alias="APPROVAL_SERVICE_URL")
    monitoring_adapter_url: str = Field(default="http://monitoring-adapter:8000", alias="MONITORING_ADAPTER_URL")
    api_gateway_url: str = Field(default="http://api-gateway:8000", alias="API_GATEWAY_URL")
    kafka_enabled: bool = Field(default=True, alias="KAFKA_ENABLED")
    kafka_startup_attempts: int = Field(default=30, alias="KAFKA_STARTUP_ATTEMPTS")
    kafka_startup_retry_seconds: float = Field(default=2.0, alias="KAFKA_STARTUP_RETRY_SECONDS")
    database_enabled: bool = Field(default=True, alias="DATABASE_ENABLED")
    local_llm_endpoint: str = Field(default="http://ollama:11434", alias="LOCAL_LLM_ENDPOINT")
    local_llm_enabled: bool = Field(default=False, alias="LOCAL_LLM_ENABLED")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_gpt5_model: str = Field(default="gpt-5", alias="OPENAI_GPT5_MODEL")
    openai_gpt4o_model: str = Field(default="gpt-4o", alias="OPENAI_GPT4O_MODEL")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        alias="GEMINI_BASE_URL",
    )
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1", alias="GROQ_BASE_URL")
    llm_request_timeout_seconds: float = Field(default=120.0, alias="LLM_REQUEST_TIMEOUT_SECONDS")
    gateway_request_timeout_seconds: float = Field(default=180.0, alias="GATEWAY_REQUEST_TIMEOUT_SECONDS")
    openai_gpt5_input_cost_per_million: float = Field(default=1.25, alias="OPENAI_GPT5_INPUT_COST_PER_MILLION")
    openai_gpt5_output_cost_per_million: float = Field(default=10.0, alias="OPENAI_GPT5_OUTPUT_COST_PER_MILLION")
    openai_gpt4o_input_cost_per_million: float = Field(default=2.5, alias="OPENAI_GPT4O_INPUT_COST_PER_MILLION")
    openai_gpt4o_output_cost_per_million: float = Field(default=10.0, alias="OPENAI_GPT4O_OUTPUT_COST_PER_MILLION")
    gemini_input_cost_per_million: float = Field(default=0.075, alias="GEMINI_INPUT_COST_PER_MILLION")
    gemini_output_cost_per_million: float = Field(default=0.30, alias="GEMINI_OUTPUT_COST_PER_MILLION")
    groq_input_cost_per_million: float = Field(default=0.59, alias="GROQ_INPUT_COST_PER_MILLION")
    groq_output_cost_per_million: float = Field(default=0.79, alias="GROQ_OUTPUT_COST_PER_MILLION")

    @model_validator(mode="after")
    def configure_database_url(self) -> "Settings":
        if self.database_url and not self.database_url.startswith("postgresql+asyncpg://kaiops:kaiops@localhost:5432/kaiops"):
            return self

        if self.db.lower() == "mysql":
            self.database_url = (
                f"mysql+aiomysql://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
                f"@{self.db_host}:{self.db_port}/{self.db_database}"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
