from __future__ import annotations

from opentelemetry import trace
try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
except (ImportError, Exception):
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except (ImportError, Exception):
        OTLPSpanExporter = None

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

from common.config import Settings
from common.logging import get_logger

logger = get_logger(__name__)

EVENTS_PROCESSED = Counter(
    "kaiops_events_processed_total",
    "Events processed by service and topic",
    ["service", "topic", "status"],
)
REQUEST_LATENCY = Histogram(
    "kaiops_request_latency_seconds",
    "Application request latency by service and operation",
    ["service", "operation"],
)
EVENT_PUBLISH_LATENCY = Histogram(
    "kaiops_event_publish_latency_seconds",
    "Event publish latency by service, topic, and producer agent",
    ["service", "topic", "agent"],
)
EVENT_CONTRACTS_EMITTED = Counter(
    "kaiops_event_contracts_emitted_total",
    "Count of emitted event contracts by version",
    ["service", "topic", "agent", "version"],
)
AGENT_STAGE_LATENCY = Histogram(
    "kaiops_agent_stage_latency_seconds",
    "Agent runtime stage latency in seconds",
    ["agent", "stage"],
)
AGENT_EXECUTIONS = Counter(
    "kaiops_agent_executions_total",
    "Agent runtime execution outcomes",
    ["agent", "status"],
)
APPLICATIONS_ONBOARDED = Counter(
    "applications_onboarded_total",
    "Applications registered for monitoring onboarding",
    ["tenant", "environment", "status"],
)
ONBOARDING_SUCCESS = Counter(
    "onboarding_success_total",
    "Successful monitoring onboarding executions",
    ["service", "stage"],
)
ONBOARDING_FAILED = Counter(
    "onboarding_failed_total",
    "Failed monitoring onboarding executions",
    ["service", "stage"],
)
APPLICATION_DISCOVERY_DURATION = Histogram(
    "application_discovery_duration",
    "Application discovery duration in seconds",
    ["service", "provider"],
)
RULE_GENERATION_DURATION = Histogram(
    "rule_generation_duration",
    "Monitoring rule generation duration in seconds",
    ["service", "provider"],
)
VALIDATION_DURATION = Histogram(
    "validation_duration",
    "Monitoring validation duration in seconds",
    ["service", "provider"],
)
DASHBOARD_GENERATION_DURATION = Histogram(
    "dashboard_generation_duration",
    "Grafana dashboard generation duration in seconds",
    ["service", "provider"],
)

CONTEXT_STRATEGY_REQUESTS = Counter(
    "kaiops_context_strategy_requests_total",
    "Context processing requests by strategy and outcome",
    ["strategy", "outcome"],
)
CONTEXT_STRATEGY_DURATION = Histogram(
    "kaiops_context_strategy_duration_seconds",
    "End-to-end context processing latency by strategy and path",
    ["strategy", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
CONTEXT_KNOWLEDGE_OPERATIONS = Counter(
    "kaiops_context_knowledge_operations_total",
    "Durable context knowledge operations by operation and result",
    ["operation", "result"],
)
CONTEXT_KNOWLEDGE_REUSE_COUNT = Histogram(
    "kaiops_context_knowledge_reuse_count",
    "Observed reuse count for context knowledge cache hits",
    buckets=(1, 2, 3, 5, 10, 25, 50, 100, 250, 500, 1000),
)
WORKFLOW_LATENCY = Histogram("kaiops_workflow_latency_seconds", "Workflow activity duration by workflow, stage, and outcome", ["workflow", "stage", "outcome"])
WORKFLOW_FAILURES = Counter("kaiops_workflow_failures_total", "Workflow failures by workflow and stage", ["workflow", "stage"])
QUEUE_DEPTH = Gauge("kaiops_queue_depth", "Broker-reported queue depth", ["provider", "queue"])
QUEUE_AGE = Histogram("kaiops_queue_age_seconds", "Age of a message when consumed", ["provider", "queue"])
DEAD_LETTER_EVENTS = Counter("kaiops_dead_letter_events_total", "Events sent to dead letter", ["provider", "queue", "reason"])
CONNECTOR_LATENCY = Histogram("kaiops_connector_latency_seconds", "External connector latency", ["connector", "operation", "outcome"])
CONNECTOR_FAILURES = Counter("kaiops_connector_failures_total", "External connector failures", ["connector", "operation"])
MYSQL_QUERY_LATENCY = Histogram("kaiops_mysql_query_latency_seconds", "MySQL query latency by operation", ["database", "operation"])
OBJECT_STORAGE_LATENCY = Histogram("kaiops_object_storage_latency_seconds", "Object storage latency", ["provider", "operation", "outcome"])
LLM_LATENCY = Histogram("kaiops_llm_latency_seconds", "Model request latency", ["provider", "task", "outcome"])
LLM_TOKENS = Counter("kaiops_llm_tokens_total", "Model tokens by provider and direction", ["provider", "direction"])
LLM_COST_USD = Counter("kaiops_llm_cost_usd_total", "Estimated model cost in USD", ["provider"])
LLM_FALLBACKS = Counter("kaiops_llm_fallback_total", "Model fallback attempts", ["primary", "fallback"])


def setup_tracing(app, settings: Settings) -> None:
    resource = Resource.create({"service.name": settings.service_name})
    provider = TracerProvider(resource=resource)
    if settings.otlp_endpoint and OTLPSpanExporter is not None:
        try:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint)))
        except Exception as exc:
            logger.warning("Failed to initialize OTLP Span Processor", extra={"error": str(exc)})

    if getattr(settings, "observability_azure_monitor_enabled", False):
        _add_azure_monitor_exporter(provider, settings)
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    if not getattr(HTTPXClientInstrumentor(), "is_instrumented_by_opentelemetry", False):
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)


def _add_azure_monitor_exporter(provider: TracerProvider, settings: Settings) -> None:
    """Additive Azure Monitor exporter alongside any OTLP exporter."""
    connection_string = str(getattr(settings, "azure_monitor_connection_string", "") or "").strip()
    if not connection_string:
        logger.warning("azure monitor export requested but AZURE_MONITOR_CONNECTION_STRING is not set; skipping")
        return
    try:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
    except ImportError:
        logger.warning("azure monitor exporter requested but azure-monitor-opentelemetry-exporter is not installed")
        return
    try:
        provider.add_span_processor(BatchSpanProcessor(AzureMonitorTraceExporter(connection_string=connection_string)))
        logger.info("connected azure monitor trace exporter")
    except Exception as exc:
        logger.warning("failed to initialize azure monitor trace exporter", extra={"error": str(exc)})


def metrics_response() -> Response:
    return Response(generate_latest(), media_type="text/plain; version=0.0.4")
