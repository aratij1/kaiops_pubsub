from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_LOCAL_AUTH_PLACEHOLDER_VALUES = {
    "JWT_SECRET_KEY": {"change-me-in-prod", "kaiops-local-demo-secret-key-change-me"},
    "ADMIN_USER_PASSWORD": {"Admin@123456"},
    "EXECUTIVE_USER_PASSWORD": {"Executive@123456"},
    "L3_USER_PASSWORD": {"L3Engineer@123456"},
    "L2_USER_PASSWORD": {"L2Engineer@123456"},
    "L1_USER_PASSWORD": {"L1Operator@123456"},
}

_LOCAL_MYSQL_DEFAULT_URL = "mysql+aiomysql://kaiops:kaiops@localhost:3306/kaiops"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = Field(default="kaiops-service", alias="SERVICE_NAME")
    environment: str = Field(default="local", alias="ENVIRONMENT")
    cloud_provider: str = Field(default="cloud-neutral", alias="CLOUD_PROVIDER")
    deployment_profile: str = Field(default="cloud-neutral", alias="DEPLOYMENT_PROFILE")
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_group_id: str = Field(default="kaiops", alias="KAFKA_GROUP_ID")
    kafka_consumer_max_retries: int = Field(default=3, alias="KAFKA_CONSUMER_MAX_RETRIES")
    kafka_dlq_suffix: str = Field(default=".dlq", alias="KAFKA_DLQ_SUFFIX")
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost/", alias="RABBITMQ_URL")
    rabbitmq_exchange: str = Field(default="kaiops.events", alias="RABBITMQ_EXCHANGE")
    rabbitmq_queue_prefix: str = Field(default="kaiops", alias="RABBITMQ_QUEUE_PREFIX")
    rabbitmq_consumer_max_retries: int = Field(default=3, alias="RABBITMQ_CONSUMER_MAX_RETRIES")
    rabbitmq_consumer_prefetch_count: int = Field(default=10, alias="RABBITMQ_CONSUMER_PREFETCH_COUNT")
    rabbitmq_transient_requeue_enabled: bool = Field(default=False, alias="RABBITMQ_TRANSIENT_REQUEUE_ENABLED")
    rabbitmq_handler_timeout_seconds: float = Field(default=120.0, alias="RABBITMQ_HANDLER_TIMEOUT_SECONDS")
    rabbitmq_dlq_suffix: str = Field(default=".dlq", alias="RABBITMQ_DLQ_SUFFIX")
    rabbitmq_startup_attempts: int = Field(default=30, alias="RABBITMQ_STARTUP_ATTEMPTS")
    rabbitmq_startup_retry_seconds: float = Field(default=2.0, alias="RABBITMQ_STARTUP_RETRY_SECONDS")
    rabbitmq_publisher_channel_pool_size: int = Field(default=4, alias="RABBITMQ_PUBLISHER_CHANNEL_POOL_SIZE")
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
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")
    db_pool_timeout_seconds: float = Field(default=30.0, alias="DB_POOL_TIMEOUT_SECONDS")
    db_pool_recycle_seconds: int = Field(default=1800, alias="DB_POOL_RECYCLE_SECONDS")
    alerts_table_metric_interval_seconds: float = Field(
        default=300.0,
        alias="ALERTS_TABLE_METRIC_INTERVAL_SECONDS",
    )
    otlp_endpoint: str | None = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    model_router_url: str = Field(default="http://model-router:8000", alias="MODEL_ROUTER_URL")
    context_agent_url: str = Field(default="http://context-agent:8000", alias="CONTEXT_AGENT_URL")
    resolution_agent_url: str = Field(default="http://resolution-agent:8000", alias="RESOLUTION_AGENT_URL")
    approval_service_url: str = Field(default="http://approval-service:8000", alias="APPROVAL_SERVICE_URL")
    orchestrator_url: str = Field(default="http://orchestrator:8000", alias="ORCHESTRATOR_URL")
    remediation_engine_url: str = Field(default="http://remediation-engine:8000", alias="REMEDIATION_ENGINE_URL")
    monitoring_adapter_url: str = Field(default="http://monitoring-adapter:8000", alias="MONITORING_ADAPTER_URL")
    evaluation_service_url: str = Field(default="http://evaluation-service:8000", alias="EVALUATION_SERVICE_URL")
    knowledge_development_url: str = Field(default="http://knowledge-development-worker:8000", alias="KNOWLEDGE_DEVELOPMENT_URL")
    api_gateway_url: str = Field(default="http://api-gateway:8000", alias="API_GATEWAY_URL")
    application_onboarding_url: str = Field(default="http://application-onboarding:8000", alias="APPLICATION_ONBOARDING_URL")
    ai_layer_mode: str = Field(default="endpoint", alias="AI_LAYER_MODE")
    ai_layer_request_timeout_seconds: float = Field(default=120.0, alias="AI_LAYER_REQUEST_TIMEOUT_SECONDS")
    ai_layer_auth_token: str = Field(default="", alias="AI_LAYER_AUTH_TOKEN")
    context_strategy: str = Field(default="auto", alias="CONTEXT_STRATEGY")
    # Zero keeps quality-approved alert-type knowledge until evidence invalidates
    # it. Operators may set a positive TTL when their topology requires periodic
    # forced refreshes.
    context_knowledge_ttl_seconds: int = Field(default=0, alias="CONTEXT_KNOWLEDGE_TTL_SECONDS", ge=0)
    context_resolution_reuse_enabled: bool = Field(default=True, alias="CONTEXT_RESOLUTION_REUSE_ENABLED")
    context_resolution_reuse_min_score: float = Field(default=0.7, alias="CONTEXT_RESOLUTION_REUSE_MIN_SCORE", ge=0.0, le=1.0)
    object_storage_enabled: bool = Field(default=False, alias="OBJECT_STORAGE_ENABLED")
    object_storage_provider: str = Field(default="s3", alias="OBJECT_STORAGE_PROVIDER")
    object_storage_bucket: str = Field(default="kaiops-archive", alias="OBJECT_STORAGE_BUCKET")
    object_storage_endpoint_url: str = Field(default="", alias="OBJECT_STORAGE_ENDPOINT_URL")
    object_storage_region: str = Field(default="us-east-1", alias="OBJECT_STORAGE_REGION")
    object_storage_access_key: str = Field(default="", alias="OBJECT_STORAGE_ACCESS_KEY")
    object_storage_secret_key: str = Field(default="", alias="OBJECT_STORAGE_SECRET_KEY")
    azure_blob_connection_string: str = Field(default="", alias="AZURE_BLOB_CONNECTION_STRING")
    object_storage_signed_url_seconds: int = Field(default=300, alias="OBJECT_STORAGE_SIGNED_URL_SECONDS")
    prometheus_url: str = Field(default="http://prometheus:9090", alias="PROMETHEUS_URL")
    grafana_url: str = Field(default="http://grafana:3000", alias="GRAFANA_URL")
    kafka_enabled: bool = Field(default=True, alias="KAFKA_ENABLED")
    event_bus_provider: str = Field(default="rabbitmq", alias="EVENT_BUS_PROVIDER")
    message_bus_dynamic_routing: bool = Field(default=True, alias="MESSAGE_BUS_DYNAMIC_ROUTING")
    message_bus_stream_threshold: int = Field(default=500, alias="MESSAGE_BUS_STREAM_THRESHOLD")
    message_bus_default_provider: str = Field(default="rabbitmq", alias="MESSAGE_BUS_DEFAULT_PROVIDER")
    azure_service_bus_enabled: bool = Field(default=False, alias="AZURE_SERVICE_BUS_ENABLED")
    azure_service_bus_connection_string: str = Field(default="", alias="AZURE_SERVICE_BUS_CONNECTION_STRING")
    azure_service_bus_topic_prefix: str = Field(default="kaiops", alias="AZURE_SERVICE_BUS_TOPIC_PREFIX")
    azure_service_bus_subscription_prefix: str = Field(default="kaiops", alias="AZURE_SERVICE_BUS_SUBSCRIPTION_PREFIX")
    azure_service_bus_dlq_suffix: str = Field(default=".dlq", alias="AZURE_SERVICE_BUS_DLQ_SUFFIX")
    azure_service_bus_consumer_max_retries: int = Field(default=3, alias="AZURE_SERVICE_BUS_CONSUMER_MAX_RETRIES")
    azure_service_bus_pull_max_messages: int = Field(default=10, alias="AZURE_SERVICE_BUS_PULL_MAX_MESSAGES")
    azure_content_safety_enabled: bool = Field(default=False, alias="AZURE_CONTENT_SAFETY_ENABLED")
    azure_content_safety_endpoint: str = Field(default="", alias="AZURE_CONTENT_SAFETY_ENDPOINT")
    azure_content_safety_api_key: str | None = Field(default=None, alias="AZURE_CONTENT_SAFETY_API_KEY")
    azure_content_safety_api_version: str = Field(default="2024-09-01", alias="AZURE_CONTENT_SAFETY_API_VERSION")
    azure_content_safety_timeout_seconds: float = Field(default=8.0, alias="AZURE_CONTENT_SAFETY_TIMEOUT_SECONDS")
    azure_content_safety_sanitize_responses: bool = Field(default=False, alias="AZURE_CONTENT_SAFETY_SANITIZE_RESPONSES")
    azure_openai_embeddings_enabled: bool = Field(default=False, alias="AZURE_OPENAI_EMBEDDINGS_ENABLED")
    azure_openai_endpoint: str = Field(default="", alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str | None = Field(default=None, alias="AZURE_OPENAI_API_KEY")
    azure_openai_embeddings_deployment: str = Field(default="", alias="AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT")
    azure_openai_api_version: str = Field(default="2024-06-01", alias="AZURE_OPENAI_API_VERSION")
    azure_openai_embeddings_timeout_seconds: float = Field(default=8.0, alias="AZURE_OPENAI_EMBEDDINGS_TIMEOUT_SECONDS")
    rag_embedding_provider: str = Field(default="auto", alias="RAG_EMBEDDING_PROVIDER")
    rag_embedding_batch_size: int = Field(default=24, alias="RAG_EMBEDDING_BATCH_SIZE")
    rag_embedding_max_retries: int = Field(default=3, alias="RAG_EMBEDDING_MAX_RETRIES")
    rag_embedding_retry_backoff_seconds: float = Field(default=1.0, alias="RAG_EMBEDDING_RETRY_BACKOFF_SECONDS")
    openai_embedding_model: str = Field(default="text-embedding-3-large", alias="OPENAI_EMBEDDING_MODEL")
    openai_embeddings_timeout_seconds: float = Field(default=15.0, alias="OPENAI_EMBEDDINGS_TIMEOUT_SECONDS")
    rag_embedding_max_input_chars: int = Field(default=12000, alias="RAG_EMBEDDING_MAX_INPUT_CHARS")
    kafka_session_timeout_ms: int = Field(default=45000, alias="KAFKA_SESSION_TIMEOUT_MS")
    kafka_heartbeat_interval_ms: int = Field(default=15000, alias="KAFKA_HEARTBEAT_INTERVAL_MS")
    kafka_max_poll_interval_ms: int = Field(default=300000, alias="KAFKA_MAX_POLL_INTERVAL_MS")
    azure_ai_search_enabled: bool = Field(default=False, alias="AZURE_AI_SEARCH_ENABLED")
    azure_ai_search_endpoint: str = Field(default="", alias="AZURE_AI_SEARCH_ENDPOINT")
    azure_ai_search_api_key: str | None = Field(default=None, alias="AZURE_AI_SEARCH_API_KEY")
    azure_ai_search_index_name: str = Field(default="kaiops-rag", alias="AZURE_AI_SEARCH_INDEX_NAME")
    azure_ai_search_api_version: str = Field(default="2024-07-01", alias="AZURE_AI_SEARCH_API_VERSION")
    azure_ai_search_content_field: str = Field(default="content", alias="AZURE_AI_SEARCH_CONTENT_FIELD")
    azure_ai_search_vector_field: str = Field(default="content_vector", alias="AZURE_AI_SEARCH_VECTOR_FIELD")
    azure_ai_search_timeout_seconds: float = Field(default=8.0, alias="AZURE_AI_SEARCH_TIMEOUT_SECONDS")
    azure_ai_evaluation_enabled: bool = Field(default=False, alias="AZURE_AI_EVALUATION_ENABLED")
    azure_ai_evaluation_deployment: str = Field(default="", alias="AZURE_AI_EVALUATION_DEPLOYMENT")
    azure_ai_evaluation_metric: str = Field(default="coherence", alias="AZURE_AI_EVALUATION_METRIC")
    azure_ai_evaluation_metrics: str = Field(default="", alias="AZURE_AI_EVALUATION_METRICS")
    azure_ai_evaluation_timeout_seconds: float = Field(default=8.0, alias="AZURE_AI_EVALUATION_TIMEOUT_SECONDS")
    observability_azure_monitor_enabled: bool = Field(default=False, alias="OBSERVABILITY_AZURE_MONITOR_ENABLED")
    azure_monitor_connection_string: str = Field(default="", alias="AZURE_MONITOR_CONNECTION_STRING")
    orchestration_config_path: str = Field(default="", alias="ORCHESTRATION_CONFIG_PATH")
    connection_config_path: str = Field(default="backend/config/kaiops-connections.json", alias="CONNECTION_CONFIG_PATH")
    message_bus_worker_count: int = Field(default=1, alias="MESSAGE_BUS_WORKER_COUNT")
    temporal_pilot_enabled: bool = Field(default=False, alias="TEMPORAL_PILOT_ENABLED")
    temporal_address: str = Field(default="temporal:7233", alias="TEMPORAL_ADDRESS")
    temporal_namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")
    temporal_task_queue: str = Field(default="kaiops-incident-pilot", alias="TEMPORAL_TASK_QUEUE")
    remediation_temporal_enabled: bool = Field(default=False, alias="REMEDIATION_TEMPORAL_ENABLED")
    remediation_temporal_task_queue: str = Field(default="kaiops-remediation", alias="REMEDIATION_TEMPORAL_TASK_QUEUE")
    remediation_internal_token: str = Field(default="", alias="REMEDIATION_INTERNAL_TOKEN")
    temporal_approval_timeout_hours: int = Field(default=24, alias="TEMPORAL_APPROVAL_TIMEOUT_HOURS")
    orchestration_llm_planner_enabled: bool = Field(default=False, alias="ORCHESTRATION_LLM_PLANNER_ENABLED")
    kafka_startup_attempts: int = Field(default=30, alias="KAFKA_STARTUP_ATTEMPTS")
    kafka_startup_retry_seconds: float = Field(default=2.0, alias="KAFKA_STARTUP_RETRY_SECONDS")
    database_enabled: bool = Field(default=True, alias="DATABASE_ENABLED")
    model_gateway_provider: str = Field(default="router", alias="MODEL_GATEWAY_PROVIDER")
    alert_correlation_threshold: float = Field(default=0.72, alias="ALERT_CORRELATION_THRESHOLD")
    alert_retention_minutes: int = Field(default=60, alias="ALERT_RETENTION_MINUTES")
    alert_correlation_candidate_limit: int = Field(default=250, alias="ALERT_CORRELATION_CANDIDATE_LIMIT")
    alert_deduplication_enabled: bool = Field(default=True, alias="ALERT_DEDUPLICATION_ENABLED")
    alert_deduplication_window_minutes: int = Field(default=60, alias="ALERT_DEDUPLICATION_WINDOW_MINUTES")
    confidence_auto_execute_threshold: float = Field(default=0.9, alias="CONFIDENCE_AUTO_EXECUTE_THRESHOLD")
    confidence_guided_execute_threshold: float = Field(default=0.75, alias="CONFIDENCE_GUIDED_EXECUTE_THRESHOLD")
    auto_execute_min_confidence: float = Field(default=0.8, alias="AUTO_EXECUTE_MIN_CONFIDENCE")
    # Arch's auto-completion rule: when both the RCA confidence and the
    # resolution (remediation recommendation) confidence meet this threshold,
    # the alert flow continues without waiting on manual approval. Below
    # threshold on either value, the existing approval flow is unchanged.
    rca_resolution_auto_complete_threshold: float = Field(
        default=0.70, alias="RCA_RESOLUTION_AUTO_COMPLETE_THRESHOLD"
    )
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
    reasoning_standard_model: str = Field(default="gpt-5.6-terra", alias="REASONING_STANDARD_MODEL")
    reasoning_critical_model: str = Field(default="gpt-5.6-sol", alias="REASONING_CRITICAL_MODEL")
    model_router_reasoning_backend: str = Field(default="openai", alias="MODEL_ROUTER_REASONING_BACKEND")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        alias="GEMINI_BASE_URL",
    )
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1", alias="GROQ_BASE_URL")
    # Separate from azure_openai_embeddings_deployment above (used only for RAG
    # embeddings) and azure_ai_evaluation_deployment (used only for the LLM-judge
    # groundedness scorer) — this is the deployment model-router's own
    # AzureOpenAIModelProvider calls for RCA/impact/fix chat completions.
    # Defaults to "gpt-4o" since that's the deployment already proven live on
    # this endpoint via the evaluation client.
    azure_openai_chat_deployment: str = Field(default="gpt-4o", alias="AZURE_OPENAI_CHAT_DEPLOYMENT")
    llm_request_timeout_seconds: float = Field(default=120.0, alias="LLM_REQUEST_TIMEOUT_SECONDS")
    model_router_prompt_cache_enabled: bool = Field(default=True, alias="MODEL_ROUTER_PROMPT_CACHE_ENABLED")
    model_router_prompt_cache_ttl_seconds: float = Field(default=300.0, alias="MODEL_ROUTER_PROMPT_CACHE_TTL_SECONDS")
    model_router_prompt_cache_max_entries: int = Field(default=512, alias="MODEL_ROUTER_PROMPT_CACHE_MAX_ENTRIES")
    model_router_max_prompt_chars: int = Field(default=60000, alias="MODEL_ROUTER_MAX_PROMPT_CHARS")
    model_router_max_payload_bytes: int = Field(default=750000, alias="MODEL_ROUTER_MAX_PAYLOAD_BYTES")
    model_router_critical_provider: str = Field(default="reasoning-critical", alias="MODEL_ROUTER_CRITICAL_PROVIDER")
    model_router_rca_provider: str = Field(default="reasoning-standard", alias="MODEL_ROUTER_RCA_PROVIDER")
    model_router_default_provider: str = Field(default="gpt-4o", alias="MODEL_ROUTER_DEFAULT_PROVIDER")
    model_router_evaluation_policy_path: str = Field(
        default="backend/evaluation/model-routing-policy.json",
        alias="MODEL_ROUTER_EVALUATION_POLICY_PATH",
    )
    model_router_evaluation_min_cases: int = Field(default=50, alias="MODEL_ROUTER_EVALUATION_MIN_CASES")
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
    auth_mode: str = Field(default="local", alias="AUTH_MODE")
    oidc_issuer: str = Field(default="", alias="OIDC_ISSUER")
    oidc_audience: str = Field(default="", alias="OIDC_AUDIENCE")
    oidc_client_id: str = Field(default="", alias="OIDC_CLIENT_ID")
    oidc_role_claim: str = Field(default="roles", alias="OIDC_ROLE_CLAIM")
    oidc_tenant_claim: str = Field(default="tenant_id", alias="OIDC_TENANT_CLAIM")
    oidc_role_mappings: str = Field(default="", alias="OIDC_ROLE_MAPPINGS")
    oidc_jwks_cache_seconds: int = Field(default=3600, alias="OIDC_JWKS_CACHE_SECONDS")
    oidc_step_up_values: str = Field(default="mfa,c2,c3", alias="OIDC_STEP_UP_VALUES")
    trust_x_forwarded_for: bool = Field(default=False, alias="TRUST_X_FORWARDED_FOR")
    admin_user_password: str = Field(default="Admin@123456", alias="ADMIN_USER_PASSWORD")
    executive_user_password: str = Field(default="Executive@123456", alias="EXECUTIVE_USER_PASSWORD")
    l3_user_password: str = Field(default="L3Engineer@123456", alias="L3_USER_PASSWORD")
    l2_user_password: str = Field(default="L2Engineer@123456", alias="L2_USER_PASSWORD")
    l1_user_password: str = Field(default="L1Operator@123456", alias="L1_USER_PASSWORD")

    smtp_enabled: bool = Field(default=False, alias="SMTP_ENABLED")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_from_address: str = Field(default="kaiops-alerts@kaiops.local", alias="SMTP_FROM_ADDRESS")
    notification_recipient_emails: str = Field(default="", alias="NOTIFICATION_RECIPIENT_EMAILS")
    teams_enabled: bool = Field(default=False, alias="TEAMS_ENABLED")
    teams_webhook_url: str = Field(default="", alias="TEAMS_WEBHOOK_URL")
    notification_min_alert_severity: str = Field(default="high", alias="NOTIFICATION_MIN_ALERT_SEVERITY")
    notification_incident_poll_interval_seconds: float = Field(
        default=15.0, alias="NOTIFICATION_INCIDENT_POLL_INTERVAL_SECONDS"
    )

    @model_validator(mode="after")
    def configure_database_url(self) -> "Settings":
        profile = str(self.deployment_profile or "cloud-neutral").strip().lower()
        profile_aliases = {
            "azure": "azure-cloud",
            "aws-cloud": "aws",
            "gcp-cloud": "gcp",
            "multi-cloud": "cloud-neutral",
            "cloud": "cloud-neutral",
        }
        profile = profile_aliases.get(profile, profile)
        if profile not in {"onprem", "local", "private-cloud", "azure-cloud", "aws", "gcp", "cloud-neutral"}:
            self.deployment_profile = "cloud-neutral"
        else:
            self.deployment_profile = profile
        provider = str(self.cloud_provider or "").strip().lower() or "cloud-neutral"
        provider_aliases = {
            "azure-cloud": "azure",
            "aws-cloud": "aws",
            "gcp-cloud": "gcp",
            "onprem": "onprem",
            "on-prem": "onprem",
            "multi-cloud": "cloud-neutral",
            "cloud": "cloud-neutral",
        }
        self.cloud_provider = provider_aliases.get(provider, provider)

        if self.database_url and self.database_url != _LOCAL_MYSQL_DEFAULT_URL:
            normalized_url = self.database_url.strip().lower()
            sqlite_test_url = normalized_url.startswith("sqlite") and self.environment.strip().lower() in {"local", "demo", "test"}
            if not normalized_url.startswith(("mysql://", "mysql+aiomysql://")) and not sqlite_test_url:
                raise ValueError("KaiOps production persistence supports only MySQL DATABASE_URL values")
            self._validate_auth_secrets()
            return self

        if self.db.lower() != "mysql":
            raise ValueError("DB must be mysql; alternate relational databases are prohibited")
        self.database_url = (
            f"mysql+aiomysql://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_database}"
        )

        self._validate_auth_secrets()
        return self

    def _validate_auth_secrets(self) -> None:
        environment = self.environment.strip().lower()
        auth_mode = self.auth_mode.strip().lower()
        if auth_mode not in {"local", "oidc"}:
            raise ValueError("AUTH_MODE must be local or oidc")
        self.auth_mode = auth_mode
        if environment in {"local", "demo", "test"}:
            return

        if auth_mode != "oidc":
            raise ValueError("Production requires AUTH_MODE=oidc; local password authentication is development-only")
        missing_oidc = [name for name in ("oidc_issuer", "oidc_audience", "oidc_client_id") if not str(getattr(self, name)).strip()]
        if missing_oidc:
            raise ValueError(f"Missing production OIDC settings: {', '.join(name.upper() for name in missing_oidc)}")
        if not self.oidc_issuer.lower().startswith("https://"):
            raise ValueError("Production OIDC_ISSUER must use HTTPS")
        # Local JWT keys and seeded passwords are not authentication inputs in
        # OIDC mode; do not force operators to create unused production secrets.
        return

        placeholder_fields = [
            field_name
            for field_name, placeholders in _LOCAL_AUTH_PLACEHOLDER_VALUES.items()
            if getattr(self, field_name.lower()) in placeholders
        ]
        if placeholder_fields:
            fields = ", ".join(sorted(placeholder_fields))
            raise ValueError(f"Missing production auth secrets: {fields}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
