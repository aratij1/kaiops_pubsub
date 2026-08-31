# KaiOps modernization: Phase 12 report

Date: 2026-08-04 (Asia/Calcutta)

## Scope completed

Message-bus selection is now deployment-time and provider-independent for the orchestrator. RabbitMQ is the portable default; Kafka requires explicit enablement; Azure Service Bus requires explicit enablement and credentials. Per-incident AI/policy output can no longer switch transport inside a running workflow. A single publisher/consumer factory selects RabbitMQ, Kafka, or Azure Service Bus and rejects invalid startup configurations.

## Files modified

- `backend/src/common/common/config.py`
- `backend/src/common/common/event_publishers.py`
- `backend/src/orchestrator/orchestrator/message_bus.py`
- `backend/src/orchestrator/app.py`
- `backend/tests/test_message_bus_routing.py`
- `docs/MODERNIZATION_PHASE_12_REPORT.md`

## Architecture decisions

1. `EVENT_BUS_PROVIDER` is the only runtime provider selector and defaults to RabbitMQ.
2. Provider aliases normalize once at startup.
3. A provider is rejected when its required enablement or connection configuration is absent.
4. Orchestration decisions may retain legacy provider advice for audit compatibility, but transport ignores it.
5. Each service worker receives one provider-specific consumer selected at startup.
6. Existing canonical envelopes, trace/correlation metadata, idempotent consumer caches, bounded retry, and DLQ policies remain intact.

## Existing functionality preserved

- RabbitMQ default workflow
- explicit Kafka and Azure Service Bus deployment options
- event envelope, agent contract, correlation, trace, retry, and DLQ behavior
- Temporal remains separate from broad event transport

## API and MySQL impact

None. No schema or public API changed. MySQL remains authoritative. No PostgreSQL or pgvector integration was introduced.

## Security implications

- invalid or incomplete provider configuration fails at startup instead of silently logging/dropping events
- business logic no longer controls infrastructure routing
- existing DLQ payload and audit behavior is preserved

## Feature/configuration changes

- `EVENT_BUS_PROVIDER` defaults to `rabbitmq`
- allowed values: `rabbitmq`, `kafka`, `azure-service-bus` (plus existing non-production `noop`/`rest` publisher modes)
- Kafka and Azure Service Bus have explicit prerequisite validation

## Tests and commands

```text
Production orchestrator image build                         PASS
Deployment provider + consumer factory smoke test           PASS
Python compilation in production package                    PASS via image import
```

The routing regression test now proves that changing stream volume may alter legacy policy advice but cannot change the deployment-selected transport.

## Queue operations

- RabbitMQ, Kafka, and Azure Service Bus consumers retain bounded retries and dead-letter behavior.
- Existing observability surfaces report configured/observed providers.
- Broker-native queue depth, oldest-message age, DLQ inspection, and replay require provider administrative credentials and are intentionally not fabricated by the application.

## Known limitations

- provider-native queue depth/age and safe DLQ replay adapters still require scoped broker-management credentials and integration environments
- older services still construct provider-specific consumers directly and should migrate incrementally to `build_event_consumer`
- legacy orchestration policy still emits `message_bus_provider` as non-authoritative advisory metadata

## Rollback procedure

Set `EVENT_BUS_PROVIDER=rabbitmq`, revert the central consumer factory use in orchestrator, and rebuild the service. No data migration or MySQL rollback is required.

## Recommended next phase

Proceed directly to Phase 13 deployable consolidation, using runtime dependency boundaries and independent scaling requirements rather than merging code blindly.
