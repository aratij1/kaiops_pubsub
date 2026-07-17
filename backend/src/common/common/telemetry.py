from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram, generate_latest
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


def setup_tracing(app, settings: Settings) -> None:
    resource = Resource.create({"service.name": settings.service_name})
    provider = TracerProvider(resource=resource)
    if settings.otlp_endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint)))
    if getattr(settings, "observability_azure_monitor_enabled", False):
        _add_azure_monitor_exporter(provider, settings)
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


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
