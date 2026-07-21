# Cloud-Agnostic Scaling And Migration

This runbook makes KaiOps portable across local VMs, Azure, AWS, GCP, and Kubernetes by keeping provider choices in configuration instead of service code.

## Target Architecture

KaiOps services are stateless where possible:

- UI, API gateway, monitoring adapter, alert intelligence, orchestrator, context agent, resolution agent, approval service, remediation engine, closure service, and model router can run as multiple replicas.
- MySQL, Redis, message bus, vector index, object storage, secrets, and observability sinks must be shared external services in production.
- Every VM or Kubernetes pod should run the same image/source version and point to the same external endpoints.

## Configuration Profiles

Generate environment overrides from the shared profile map:

```powershell
python scripts/switch_service_profile.py --profile cloud-neutral --output config/env/.env.profile.generated
```

Supported profiles are defined in [service-profiles.json](../scripts/profiles/service-profiles.json). Runtime cloud selection is controlled by:

| Setting | Purpose |
| --- | --- |
| `CLOUD_PROVIDER` | `local`, `azure`, `aws`, `gcp`, or `cloud-neutral` |
| `DEPLOYMENT_PROFILE` | Operational profile used by services and deployment scripts |
| `DATABASE_URL` | Shared SQL database endpoint |
| `REDIS_URL` | Shared cache/session/idempotency endpoint |
| `EVENT_BUS_PROVIDER` | `rabbitmq`, `kafka`, or cloud bus adapter |
| `MESSAGE_BUS_DEFAULT_PROVIDER` | Default event transport |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka endpoint when Kafka is enabled |
| `RABBITMQ_URL` | RabbitMQ endpoint when RabbitMQ is enabled |
| `VECTOR_STORE_PROVIDER` | Vector store backend |
| `EMBEDDING_PROVIDER` | Embedding provider |

Use [.env.cloud.example](../config/env/.env.cloud.example) as the portable runtime template.

## Horizontal Scaling

### VM Scale-Out

Use a public or private load balancer in front of multiple identical VMs.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/deploy-to-vm.ps1 `
  -Targets 20.0.0.10,20.0.0.11,20.0.0.12 `
  -SshUser azureuser `
  -SshPrivateKey "C:\path\to\key.pem" `
  -EnvFile config/env/.env.cloud.example `
  -NoStrictHostKeyChecking
```

For VM scale-out:

- Put UI and API gateway behind the load balancer.
- Keep MySQL, Redis, RabbitMQ/Kafka, vector store, and object storage outside the app VMs.
- Use sticky sessions only if the UI depends on browser session affinity; otherwise keep traffic round-robin.
- Add VMs by running the same deploy script and registering the VM in the load balancer backend pool.

Run Compose with the scaling overlays:

```powershell
docker compose --env-file .env `
  -f docker-compose.yml `
  -f docker-compose.external-state.yml `
  -f docker-compose.scale.yml `
  up -d --build
```

`docker-compose.external-state.yml` disables local state containers unless the `local-state` profile is explicitly enabled.

### Kubernetes Scale-Out

For AKS, EKS, GKE, or self-managed Kubernetes:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/
```

The HPA baseline in [hpa.yaml](../k8s/hpa.yaml) scales API and agent workers on CPU and memory. For production queue-aware scaling, add KEDA or the equivalent cloud metric adapter for:

- RabbitMQ queue depth
- Kafka consumer lag
- alert ingestion rate
- remediation execution backlog
- model-router latency

## Vertical Scaling

Use vertical scaling when a component is CPU, memory, or connection limited before adding more replicas.

| Service | Scale Up Signal | Typical Action |
| --- | --- | --- |
| API gateway | high CPU, TLS/proxy saturation | more CPU, higher worker count |
| context agent | slow RAG/context assembly | more CPU and memory |
| resolution agent | model call concurrency and prompt assembly latency | more CPU, higher timeout budget |
| remediation engine | long command/plugin execution queue | more CPU and isolated worker pools |
| model router | request latency or provider throttling | more replicas plus provider rate limits |
| MySQL | lock waits, connection pressure, disk IOPS | managed DB tier upgrade/read replica |
| Redis | memory pressure or evictions | managed cache tier upgrade |
| vector store | slow nearest-neighbor search | larger index nodes or shard count |

## Scale Policy

Start with:

- UI: 2 replicas
- API gateway: 3 replicas
- monitoring adapter: 2 replicas
- each event agent: 2 replicas
- model router: 2 replicas
- remediation engine: 2 replicas, with risk-based concurrency limits

Scale out when any condition holds for 10 minutes:

- API p95 latency is above 1 second
- CPU is above 65%
- memory is above 75%
- RabbitMQ queue depth exceeds 1,000 messages per active worker
- Kafka consumer lag grows for 5 minutes
- model-router p95 latency is above configured provider SLO

Scale in only after 30 minutes of stable low usage. Never scale in below 2 replicas for production control-plane services.

## Cloud Migration

Migration should be a configuration and data movement exercise, not a code fork.

1. Provision target cloud shared services: SQL DB, Redis/cache, message bus, vector store, object storage, secrets, and monitoring.
2. Generate the target profile:

   ```powershell
   python scripts/switch_service_profile.py --profile aws --output config/env/.env.profile.generated
   ```

3. Merge target endpoint values into `config/env/.env.cloud.example` or your secure secret store.
4. Migrate data:
   - SQL dump/restore or managed database migration service
   - Redis warm start if required
   - vector index rebuild or snapshot restore
   - RAG document/object storage copy
   - message bus drain/replay policy
5. Deploy the same application version to the target cloud.
6. Run smoke and E2E checks:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/run_cloud_profile_e2e.ps1 -Profile cloud-neutral
   ```

7. Move load balancer/DNS traffic gradually: 5%, 25%, 50%, 100%.
8. Keep source cloud in read-only fallback until post-cutover checks pass.

## Provider Mapping

| Capability | Azure | AWS | GCP | Portable Setting |
| --- | --- | --- | --- | --- |
| Container platform | AKS / VMSS | EKS / EC2 ASG | GKE / MIG | `DEPLOYMENT_PROFILE` |
| SQL | Azure Database for MySQL | RDS MySQL/Aurora | Cloud SQL MySQL | `DATABASE_URL` |
| Cache | Azure Cache for Redis | ElastiCache Redis | Memorystore Redis | `REDIS_URL` |
| Message bus | Service Bus / RabbitMQ / Kafka | MSK / RabbitMQ / SQS adapter | Pub/Sub / Kafka / RabbitMQ | `EVENT_BUS_PROVIDER` |
| Secrets | Key Vault | Secrets Manager | Secret Manager | runtime secret injection |
| Object docs | Blob Storage | S3 | Cloud Storage | document storage adapter |
| Observability | Azure Monitor | CloudWatch | Cloud Monitoring | `OBSERVABILITY_SINK` |
| LLM | Azure OpenAI | Bedrock/OpenAI | Vertex/OpenAI | model router env |

## Production Rules

- Do not run local MySQL/Redis/message-bus containers on every app VM in production.
- Do not store JWT secrets or provider keys in git.
- Use one immutable build artifact per release and deploy it to all providers.
- Require health checks before adding a VM/pod to load balancing.
- Keep remediation execution concurrency and approval gates independent per tenant/environment.
- Preserve trace IDs through every service, queue event, RAG lookup, LLM call, approval, and remediation action.
