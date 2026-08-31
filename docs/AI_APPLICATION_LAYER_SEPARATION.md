# AI Layer And Application Layer Separation

KaiOps now treats AI services as a separate layer. Application services call AI capabilities only through HTTP endpoints.

## Layers

| Layer | Services | Responsibility |
| --- | --- | --- |
| Application layer | UI, API gateway, monitoring adapter, onboarding, orchestration, approval, remediation, closure, notification, audit | Product workflow, user/API access, governance, approval, execution, state |
| AI layer | context-agent, resolution-agent, model-router, evaluation-service | RAG/context retrieval, LangGraph resolution, model routing, quality evaluation |
| Shared platform | MySQL, Redis, RabbitMQ/Kafka, vector store, observability | Durable state, events, cache, embeddings/index, telemetry |

## Endpoint Contract

Application services use these environment variables:

```text
AI_LAYER_MODE=endpoint
AI_LAYER_REQUEST_TIMEOUT_SECONDS=120
AI_LAYER_AUTH_TOKEN=
CONTEXT_AGENT_URL=http://context-agent:8000
RESOLUTION_AGENT_URL=http://resolution-agent:8000
MODEL_ROUTER_URL=http://model-router:8000
EVALUATION_SERVICE_URL=http://evaluation-service:8000
```

The application layer calls:

| Capability | Endpoint |
| --- | --- |
| Context retrieval | `POST {CONTEXT_AGENT_URL}/collect` |
| Resolution/RCA | `POST {RESOLUTION_AGENT_URL}/resolve` |
| Model route | `POST {MODEL_ROUTER_URL}/route` |
| Evaluation | `POST {EVALUATION_SERVICE_URL}/evaluations` |

Shared client:

- [ai_layer_client.py](../backend/src/common/common/ai_layer_client.py)

## Runtime Flow

```text
Application Layer
  monitoring-adapter
    -> alert-intelligence
    -> orchestrator
    -> AiLayerClient POST /collect

AI Layer
  context-agent
    -> RAG/vector/doc/index connectors
    -> context payload

Application Layer
  monitoring-adapter
    -> AiLayerClient POST /resolve

AI Layer
  resolution-agent
    -> model-router endpoint
    -> recommendation

Application Layer
  approval-service
    -> remediation-engine
    -> closure-service
```

## VM Deployment

Application VM:

```powershell
docker compose --profile application-layer --env-file .env `
  -f docker-compose.yml `
  -f docker-compose.external-state.yml `
  -f docker-compose.layered.yml `
  up -d --build
```

AI VM:

```powershell
docker compose --profile ai-layer --env-file .env `
  -f docker-compose.yml `
  -f docker-compose.external-state.yml `
  -f docker-compose.layered.yml `
  up -d --build
```

For separate VMs, point the application `.env` to the AI VM or AI load balancer:

```text
CONTEXT_AGENT_URL=http://ai-layer.internal:8004
RESOLUTION_AGENT_URL=http://ai-layer.internal:8006
MODEL_ROUTER_URL=http://ai-layer.internal:8005
EVALUATION_SERVICE_URL=http://ai-layer.internal:8020
```

## Kubernetes Deployment

Run AI services in a separate namespace or node pool when needed:

```text
kaiops-app
  ui, api-gateway, monitoring-adapter, approval, remediation, closure

kaiops-ai
  context-agent, resolution-agent, model-router, evaluation-service
```

Then set application ConfigMap values to the AI service DNS names or ingress URLs.

## Guardrails

- Application services must not import `context_agent`, `resolution_agent`, or `model_router` packages directly.
- AI layer credentials and model keys stay only in AI deployments.
- Application layer receives AI outputs over explicit API responses and records trace/audit data.
- AI layer can be scaled independently based on RAG latency, model-router latency, queue depth, and token throughput.
