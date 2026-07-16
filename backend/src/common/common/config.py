from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_LOCAL_AUTH_PLACEHOLDER_VALUES = {
    "JWT_SECRET_KEY": "change-me-in-prod",
    "ADMIN_USER_PASSWORD": "Admin@123456",
    "EXECUTIVE_USER_PASSWORD": "Executive@123456",
    "L3_USER_PASSWORD": "L3Engineer@123456",
    "L2_USER_PASSWORD": "L2Engineer@123456",
    "L1_USER_PASSWORD": "L1Operator@123456",
}

_LOCAL_MYSQL_DEFAULT_URL = "mysql+aiomysql://kaiops:kaiops@localhost:3306/kaiops"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = Field(default="kaiops-service", alias="SERVICE_NAME")
    environment: str = Field(default="local", alias="ENVIRONMENT")
    deployment_profile: str = Field(default="onprem", alias="DEPLOYMENT_PROFILE")
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_group_id: str = Field(default="kaiops", alias="KAFKA_GROUP_ID")
    kafka_consumer_max_retries: int = Field(default=3, alias="KAFKA_CONSUMER_MAX_RETRIES")
    kafka_dlq_suffix: str = Field(default=".dlq", alias="KAFKA_DLQ_SUFFIX")
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost/", alias="RABBITMQ_URL")
    rabbitmq_exchange: str = Field(default="kaiops.events", alias="RABBITMQ_EXCHANGE")
    rabbitmq_queue_prefix: str = Field(default="kaiops", alias="RABBITMQ_QUEUE_PREFIX")
    rabbitmq_consumer_max_retries: int = Field(default=3, alias="RABBITMQ_CONSUMER_MAX_RETRIES")
    rabbitmq_dlq_suffix: str = Field(default=".dlq", alias="RABBITMQ_DLQ_SUFFIX")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    database_url: str = Field(
        default=_LOCAL_MYSQL_DEFAULT_URL,
        alias="DATABASE_URL",
    )
    db: str = Field(default="mysql", alias="DB")
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=3306, alias="DB_PORT")
    db_user: str = Field(default="kaiops", alias="DB_USER")
    db_password: str = Field(default="kaiops", alias="DB_PASSWORD")
    db_database: str = Field(default="kaiops", alias="DB_DATABASE")
    otlp_endpoint: str | None = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    model_router_url: str = Field(default="http://model-router:8000", alias="MODEL_ROUTER_URL")
    context_agent_url: str = Field(default="http://context-agent:8000", alias="CONTEXT_AGENT_URL")
    approval_service_url: str = Field(default="http://approval-service:8000", alias="APPROVAL_SERVICE_URL")
    monitoring_adapter_url: str = Field(default="http://monitoring-adapter:8000", alias="MONITORING_ADAPTER_URL")
    api_gateway_url: str = Field(default="http://api-gateway:8000", alias="API_GATEWAY_URL")
    application_onboarding_url: str = Field(default="http://application-onboarding:8000", alias="APPLICATION_ONBOARDING_URL")
    prometheus_url: str = Field(default="http://prometheus:9090", alias="PROMETHEUS_URL")
    grafana_url: str = Field(default="http://grafana:3000", alias="GRAFANA_URL")
    kafka_enabled: bool = Field(default=True, alias="KAFKA_ENABLED")
    event_bus_provider: str = Field(default="kafka", alias="EVENT_BUS_PROVIDER")
    message_bus_dynamic_routing: bool = Field(default=True, alias="MESSAGE_BUS_DYNAMIC_ROUTING")
    message_bus_stream_threshold: int = Field(default=500, alias="MESSAGE_BUS_STREAM_THRESHOLD")
    message_bus_default_provider: str = Field(default="rabbitmq", alias="MESSAGE_BUS_DEFAULT_PROVIDER")
    gcp_project_id: str = Field(default="", alias="GCP_PROJECT_ID")
    gcp_region: str = Field(default="us-central1", alias="GCP_REGION")
    gcp_pubsub_topic_prefix: str = Field(default="kaiops", alias="GCP_PUBSUB_TOPIC_PREFIX")
    gcp_pubsub_enabled: bool = Field(default=False, alias="GCP_PUBSUB_ENABLED")
    gcp_pubsub_subscription_prefix: str = Field(default="kaiops", alias="GCP_PUBSUB_SUBSCRIPTION_PREFIX")
    gcp_pubsub_dlq_suffix: str = Field(default=".dlq", alias="GCP_PUBSUB_DLQ_SUFFIX")
    gcp_pubsub_consumer_max_retries: int = Field(default=3, alias="GCP_PUBSUB_CONSUMER_MAX_RETRIES")
    gcp_pubsub_pull_max_messages: int = Field(default=10, alias="GCP_PUBSUB_PULL_MAX_MESSAGES")
    gcp_pubsub_startup_attempts: int = Field(default=30, alias="GCP_PUBSUB_STARTUP_ATTEMPTS")
    gcp_pubsub_startup_retry_seconds: float = Field(default=2.0, alias="GCP_PUBSUB_STARTUP_RETRY_SECONDS")
    vertex_model_armor_enabled: bool = Field(default=False, alias="VERTEX_MODEL_ARMOR_ENABLED")
    vertex_model_armor_template: str = Field(default="", alias="VERTEX_MODEL_ARMOR_TEMPLATE")
    vertex_model_armor_endpoint: str = Field(default="", alias="VERTEX_MODEL_ARMOR_ENDPOINT")
    vertex_model_armor_timeout_seconds: float = Field(default=8.0, alias="VERTEX_MODEL_ARMOR_TIMEOUT_SECONDS")
    orchestration_config_path: str = Field(default="", alias="ORCHESTRATION_CONFIG_PATH")
    message_bus_worker_count: int = Field(default=1, alias="MESSAGE_BUS_WORKER_COUNT")
    orchestration_llm_planner_enabled: bool = Field(default=False, alias="ORCHESTRATION_LLM_PLANNER_ENABLED")
    kafka_startup_attempts: int = Field(default=30, alias="KAFKA_STARTUP_ATTEMPTS")
    kafka_startup_retry_seconds: float = Field(default=2.0, alias="KAFKA_STARTUP_RETRY_SECONDS")
    database_enabled: bool = Field(default=True, alias="DATABASE_ENABLED")
    model_gateway_provider: str = Field(default="router", alias="MODEL_GATEWAY_PROVIDER")
    alert_correlation_threshold: float = Field(default=0.72, alias="ALERT_CORRELATION_THRESHOLD")
    alert_retention_minutes: int = Field(default=30, alias="ALERT_RETENTION_MINUTES")
    confidence_auto_execute_threshold: float = Field(default=0.9, alias="CONFIDENCE_AUTO_EXECUTE_THRESHOLD")
    confidence_guided_execute_threshold: float = Field(default=0.75, alias="CONFIDENCE_GUIDED_EXECUTE_THRESHOLD")
    auto_execute_min_confidence: float = Field(default=0.8, alias="AUTO_EXECUTE_MIN_CONFIDENCE")
    orchestration_approval_severities: str = Field(
        default="high,critical",
        alias="ORCHESTRATION_APPROVAL_SEVERITIES",
    )
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
    model_router_prompt_cache_enabled: bool = Field(default=True, alias="MODEL_ROUTER_PROMPT_CACHE_ENABLED")
    model_router_prompt_cache_ttl_seconds: float = Field(default=300.0, alias="MODEL_ROUTER_PROMPT_CACHE_TTL_SECONDS")
    model_router_prompt_cache_max_entries: int = Field(default=512, alias="MODEL_ROUTER_PROMPT_CACHE_MAX_ENTRIES")
    gateway_request_timeout_seconds: float = Field(default=180.0, alias="GATEWAY_REQUEST_TIMEOUT_SECONDS")
    openai_gpt5_input_cost_per_million: float = Field(default=1.25, alias="OPENAI_GPT5_INPUT_COST_PER_MILLION")
    openai_gpt5_output_cost_per_million: float = Field(default=10.0, alias="OPENAI_GPT5_OUTPUT_COST_PER_MILLION")
    openai_gpt4o_input_cost_per_million: float = Field(default=2.5, alias="OPENAI_GPT4O_INPUT_COST_PER_MILLION")
    openai_gpt4o_output_cost_per_million: float = Field(default=10.0, alias="OPENAI_GPT4O_OUTPUT_COST_PER_MILLION")
    gemini_input_cost_per_million: float = Field(default=0.075, alias="GEMINI_INPUT_COST_PER_MILLION")
    gemini_output_cost_per_million: float = Field(default=0.30, alias="GEMINI_OUTPUT_COST_PER_MILLION")
    groq_input_cost_per_million: float = Field(default=0.59, alias="GROQ_INPUT_COST_PER_MILLION")
    groq_output_cost_per_million: float = Field(default=0.79, alias="GROQ_OUTPUT_COST_PER_MILLION")
    jwt_secret_key: str = Field(default="change-me-in-prod", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_minutes: int = Field(default=30, alias="JWT_ACCESS_TOKEN_MINUTES")
    jwt_refresh_token_minutes: int = Field(default=1440, alias="JWT_REFRESH_TOKEN_MINUTES")
    auth_failed_login_attempts: int = Field(default=5, alias="AUTH_FAILED_LOGIN_ATTEMPTS")
    auth_lock_minutes: int = Field(default=15, alias="AUTH_LOCK_MINUTES")
    auth_password_expiry_days: int = Field(default=90, alias="AUTH_PASSWORD_EXPIRY_DAYS")
    trust_x_forwarded_for: bool = Field(default=False, alias="TRUST_X_FORWARDED_FOR")
    admin_user_password: str = Field(default="Admin@123456", alias="ADMIN_USER_PASSWORD")
    executive_user_password: str = Field(default="Executive@123456", alias="EXECUTIVE_USER_PASSWORD")
    l3_user_password: str = Field(default="L3Engineer@123456", alias="L3_USER_PASSWORD")
    l2_user_password: str = Field(default="L2Engineer@123456", alias="L2_USER_PASSWORD")
    l1_user_password: str = Field(default="L1Operator@123456", alias="L1_USER_PASSWORD")

    @model_validator(mode="after")
    def configure_database_url(self) -> "Settings":
        profile = str(self.deployment_profile or "onprem").strip().lower()
        if profile not in {"onprem", "gcp-cloud"}:
            self.deployment_profile = "onprem"
        else:
            self.deployment_profile = profile

        if self.database_url and self.database_url != _LOCAL_MYSQL_DEFAULT_URL:
            self._validate_auth_secrets()
            return self

        if self.db.lower() == "mysql":
            self.database_url = (
                f"mysql+aiomysql://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
                f"@{self.db_host}:{self.db_port}/{self.db_database}"
            )

        self._validate_auth_secrets()
        return self

    def _validate_auth_secrets(self) -> None:
        if self.environment.strip().lower() in {"local", "demo", "test"}:
            return

        placeholder_fields = [
            field_name
            for field_name, placeholder in _LOCAL_AUTH_PLACEHOLDER_VALUES.items()
            if getattr(self, field_name.lower()) == placeholder
        ]
        if placeholder_fields:
            fields = ", ".join(sorted(placeholder_fields))
            raise ValueError(f"Missing production auth secrets: {fields}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
