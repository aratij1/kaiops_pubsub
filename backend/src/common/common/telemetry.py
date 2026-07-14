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


def setup_tracing(app, settings: Settings) -> None:
    resource = Resource.create({"service.name": settings.service_name})
    provider = TracerProvider(resource=resource)
    if settings.otlp_endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint)))
    if getattr(settings, "observability_gcp_trace_enabled", False):
        _add_gcp_trace_exporter(provider, settings)
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def _add_gcp_trace_exporter(provider: TracerProvider, settings: Settings) -> None:
    """Additive: exports spans to Cloud Trace alongside any OTLP exporter already
    configured. Disabled by default (OBSERVABILITY_GCP_TRACE_ENABLED=false)."""
    project_id = str(getattr(settings, "gcp_project_id", "") or "").strip()
    if not project_id:
        logger.warning("gcp cloud trace export requested but GCP_PROJECT_ID is not set; skipping")
        return
    try:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    except ImportError:
        logger.warning("gcp cloud trace export requested but opentelemetry-exporter-gcp-trace is not installed")
        return
    try:
        provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter(project_id=project_id)))
        logger.info("connected gcp cloud trace exporter", extra={"project": project_id})
    except Exception as exc:
        logger.warning("failed to initialize gcp cloud trace exporter", extra={"error": str(exc)})


def metrics_response() -> Response:
    return Response(generate_latest(), media_type="text/plain; version=0.0.4")
