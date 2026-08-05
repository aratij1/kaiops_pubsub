# Modernization Phase 18 — OpenTelemetry and Production Signals

## Outcome

KaiOps now has a common OpenTelemetry Collector path to Jaeger and concrete Prometheus signals across HTTP, MySQL, RabbitMQ, Temporal, object storage, SSE, connectors, and model calls. Telemetry is capability-safe: instrumentation failure cannot break database or queue processing.

## Scope completed

- Added an OpenTelemetry Collector with OTLP gRPC/HTTP receivers, memory limiting, batching, sensitive-attribute removal, Prometheus export, and Jaeger trace export.
- Added Jaeger and its Grafana datasource; Prometheus scrapes collector self/export metrics.
- Enabled OTLP by default for Compose services and added HTTPX and SQLAlchemy auto-instrumentation.
- Propagated W3C trace context through RabbitMQ headers and created consumer spans.
- Added Temporal activity spans carrying workflow/activity IDs.
- Added metrics for workflow duration/failure, queue depth/age/DLQ, connector latency/failure, SSE connections/events, MySQL query latency, object-storage latency, and LLM latency/tokens/cost/fallback.
- Instrumented MySQL, RabbitMQ, S3/MinIO, Azure Blob, Temporal pilot activities, and the model router.
- Added alerts for DLQ growth, workflow failure, MySQL p95 latency, model fallback rate, and prolonged absence of SSE clients.
- Kept SQL statement text, authorization headers, request bodies, commands, tokens, and model content out of the collector pipeline.

## API and MySQL impact

No API or schema changes. SQL metrics label only database and statement operation (`SELECT`, `INSERT`, etc.), never SQL text or parameters. Existing Prometheus `/metrics` endpoints remain intact.

## Validation

- Compose configuration: passed.
- Collector configuration validation: passed.
- Prometheus rule validation: 58 rules passed.
- Production service image rebuild with HTTPX/SQLAlchemy instrumentors: passed.
- Python compile across telemetry, database, RabbitMQ, object storage, Temporal activities, and model router: passed.
- Focused database/RabbitMQ/model regressions: 28 passed.
- Initial regression run found four unsafe assumptions around test doubles; all were fixed and the complete focused suite passed.

## Operational access

- Jaeger UI: `http://localhost:16686`
- Collector OTLP: `localhost:4317` (gRPC), `localhost:4318` (HTTP)
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

## Known limitations

Azure Service Bus and Kafka expose the common event contract but do not yet have broker-admin adapters for exact queue depth/age. RabbitMQ provides the new native signals. The separate full telemetry Docker environment continues to export logs to OpenSearch; the lightweight primary Compose collector sends OTLP logs to its redacted debug exporter until a production log-backend endpoint is selected.

Browser trace propagation is supported through HTTP headers where instrumented, but the legacy React compatibility shell does not yet emit full browser spans. This belongs with the remaining frontend decomposition work.

## Rollback

Remove `OTEL_EXPORTER_OTLP_ENDPOINT` or stop the collector/Jaeger services; application traffic continues because batch exporters fail asynchronously. Remove the new instrumentation packages and metric hooks to return to direct Prometheus-only operation.

## Recommended next phase

Phase 19: deploy the five justified domains through Azure Container Apps with managed identity, Key Vault references, probes, revisions, rollback, and KEDA scaling while retaining portable Compose.
