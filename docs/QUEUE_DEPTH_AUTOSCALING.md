# Queue-depth autoscaling (KEDA)

`k8s/hpa.yaml` scales every service on CPU/memory utilization only. That is
enough for CPU-bound work, but a RabbitMQ consumer spends most of its time
waiting on I/O (broker ack, database writes, LLM calls) rather than burning
CPU. Under a real alert burst, a stalled or overloaded consumer can stay
CPU-idle while its queue backs up, and CPU/memory HPA will not scale it out.

## Recommended follow-up: KEDA

[KEDA](https://keda.sh) adds a `ScaledObject` CRD that can scale a Deployment
on RabbitMQ queue length (or Kafka consumer lag) in addition to, or instead
of, CPU/memory. It is not installed by this repository — it is a separate
operator that must be installed on the target cluster before any
`ScaledObject` manifest takes effect.

An example, not applied by default, is at
[`k8s/keda-scaledobject.yaml.example`](../k8s/keda-scaledobject.yaml.example):
it targets `alert-intelligence` (the consumer of `raw-alerts`, the first hop
after ingestion) and folds the existing CPU/memory triggers from
`alert-intelligence-hpa` into the same `ScaledObject`, since a Deployment can
only be scaled by one HPA-producing object at a time.

## Adopting it

1. Install the KEDA operator on the target cluster (Helm chart or the
   cluster's marketplace add-on).
2. Rename `k8s/keda-scaledobject.yaml.example` to `k8s/keda-scaledobject.yaml`
   (drop the `.example` suffix) so it's picked up by `kubectl apply -f k8s/`.
3. Delete the `alert-intelligence-hpa` block from `k8s/hpa.yaml` — the
   `ScaledObject` now owns that Deployment's autoscaling.
4. Tune the `value` (target queue length per replica) against observed
   steady-state depth for your traffic, not the placeholder in the example.
   Start conservative enough that scale-up happens well before the
   `RabbitMQQueueBacklog` alert in `observability/alert.rules.yml` would page.
5. Repeat the same pattern for other RabbitMQ-consuming hot-path services
   (`context-agent`, `resolution-agent`, `remediation-engine`, `closure-service`,
   `orchestrator`) using their own queue names — see the Kafka Handoff Matrix
   in [`README.md`](../README.md) for the full producer/topic/consumer list,
   and `RabbitMQConsumer.start()` in
   `backend/src/common/common/rabbitmq.py` for the exact queue naming
   convention (`{rabbitmq_queue_prefix}.{service_name}.{topic}`).

`monitoring-adapter` is intentionally excluded: it is the HTTP ingestion
entrypoint, not a queue consumer, so request-volume-driven CPU/memory scaling
is the correct signal for it.
