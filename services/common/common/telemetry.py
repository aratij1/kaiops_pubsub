from __future__ import annotations

from prometheus_client import Counter, Histogram, generate_latest
from starlette.responses import Response

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from common.config import Settings

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


def setup_tracing(app, settings: Settings) -> None:
    resource = Resource.create({"service.name": settings.service_name})
    provider = TracerProvider(resource=resource)
    if settings.otlp_endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def metrics_response() -> Response:
    return Response(generate_latest(), media_type="text/plain; version=0.0.4")
