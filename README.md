# KaiOps: Agentic Incident Resolution Platform

KaiOps is an end-to-end Python 3.12 microservice platform for agentic incident
triage, root-cause analysis, human approval, automated remediation, closure
validation, and knowledge capture.

## Workflow

```text
Monitoring Tools
  Prometheus | Grafana | Datadog | Splunk | Azure Monitor
        -> Kafka raw-alerts
        -> Alert Intelligence Agent
        -> Kafka enriched-alerts
        -> Orchestrator Agent
        -> Context Intelligence Agent
        -> Kafka context-events
        -> Resolution Intelligence Agent (LangGraph)
        -> Kafka resolution-events
        -> Human Approval Layer
        -> Kafka approval-events
        -> Remediation Automation Engine
        -> Kafka remediation-events
        -> Closure & Validation
        -> Kafka closure-events
```

## Folder Structure

```text
services/
  monitoring-adapter/      FastAPI webhook adapter for monitoring tools
  alert-intelligence/      Deduplication, correlation, severity, enrichment
  orchestrator/            Workflow decision and downstream invocation
  model-router/            GPT-4o, GPT-5, Claude, Gemini, local Llama routing
  context-agent/           CMDB, ServiceNow, Kubernetes, Jenkins, GitHub, RAG
  resolution-agent/        LangGraph RCA -> impact -> fix -> confidence
  approval-service/        Slack/Teams/email/web approval API
  remediation-engine/      Strategy plugins for Jenkins/K8s/Ansible/Terraform/API
  closure-service/         Health validation, ticket closure, KB/RCA storage
  common/                  Models, Kafka, SQLAlchemy, telemetry, resilience
  ui/                      Streamlit incident operations dashboard
database/schema.sql        PostgreSQL DDL
k8s/                       Namespace, ConfigMap, Secret, Deployments, Services, Ingress, HPA
.github/workflows/ci.yml   Lint, test, Docker build, Kubernetes validation
```

## Core APIs

| Service | Endpoint | Purpose |
| --- | --- | --- |
| monitoring-adapter | `POST /alerts` | Ingest monitoring alerts |
| monitoring-adapter | `POST /sample/payment-latency` | Trigger a sample alert |
| alert-intelligence | `POST /process` | Deduplicate, correlate, classify, enrich |
| orchestrator | `POST /decide` | Select incident workflow |
| context-agent | `POST /collect` | Collect enterprise/RAG context |
| model-router | `POST /route` | Route LLM task with failover |
| resolution-agent | `POST /resolve` | Run LangGraph RCA workflow |
| approval-service | `POST /approve` | Approve recommendation |
| approval-service | `POST /reject` | Reject recommendation |
| approval-service | `POST /modify` | Modify recommendation |
| approval-service | `GET /incident/{id}` | Fetch incident/approval queue item |
| remediation-engine | `POST /execute` | Execute approved remediation |
| closure-service | `POST /validate` | Validate health and generate final RCA |

Every FastAPI service also exposes `/healthz`, `/readyz`, and `/metrics`.

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
docker compose up --build
```

If a service logs `Unable connect to "kafka:9092"` during Docker startup, Kafka
is still booting. The Compose file includes Kafka health checks and app-level
startup retries; after pulling the latest code, restart cleanly:

```bash
docker compose down
docker compose up --build
```

If your editor reports `import common.embeddings cannot be resolved`, make sure it
is using the `.venv` interpreter created above. The repository also includes
`pyrightconfig.json` with monorepo `extraPaths` for Cursor/Pylance.

Service ports:

- UI: <http://localhost:8501>
- Monitoring adapter: <http://localhost:8001>
- Alert intelligence: <http://localhost:8002>
- Orchestrator: <http://localhost:8003>
- Context agent: <http://localhost:8004>
- Model router: <http://localhost:8005>
- Resolution agent: <http://localhost:8006>
- Approval service: <http://localhost:8007>
- Remediation engine: <http://localhost:8008>
- Closure service: <http://localhost:8009>

For local non-Docker UI runs, start the backing API services in separate
terminals before using the dashboard buttons. For example:

```bash
export KAFKA_ENABLED=false
export DATABASE_ENABLED=false
uvicorn app:app --host 0.0.0.0 --port 8001 --app-dir services/monitoring-adapter
streamlit run services/ui/app.py
```

On PowerShell, use `$env:KAFKA_ENABLED="false"` and
`$env:DATABASE_ENABLED="false"` instead of `export`.

Windows users can start the local demo services and UI with:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\scripts\run-local-windows.ps1
```

This opens separate terminals for:

- `monitoring-adapter` on <http://localhost:8001>
- `approval-service` on <http://localhost:8007>
- Streamlit UI on <http://localhost:8501>

If Streamlit shows `WinError 10061`, the target FastAPI service is not running
on the expected port. Start it with the helper script above or run the service
manually in a separate terminal.

When running locally with `KAFKA_ENABLED=false`, `POST /sample/payment-latency`
only creates and publishes the alert through the monitoring adapter. Because
Kafka is disabled, no downstream service will consume `raw-alerts`. For a local
end-to-end demo without Kafka, use the Streamlit **Run payment latency
workflow** button or call:

```powershell
Invoke-RestMethod -Method Post http://localhost:8001/sample/payment-latency/workflow
```

That local endpoint runs alert intelligence, orchestration, context collection,
and resolution recommendation generation in-process for demo purposes.

## Kubernetes

```bash
kubectl apply -f k8s/
```

The manifests include:

- Namespace
- ConfigMap
- Secret
- Deployments
- Services
- Ingress
- HorizontalPodAutoscaler

Replace the sample image names in `k8s/services.yaml` with your registry images.

## Sample Alert-to-Remediation Flow

1. Inject a sample critical payment alert:

   ```bash
   curl -X POST http://localhost:8001/sample/payment-latency
   ```

2. `alert-intelligence` consumes `raw-alerts`, deduplicates by fingerprint,
   correlates with hashing embeddings, classifies as `critical`, enriches with
   owner/runbook metadata, persists `alerts` and `incidents`, and emits
   `enriched-alerts`.

3. `orchestrator` selects the `critical-auto-remediation` workflow and invokes
   `context-agent`.

4. `context-agent` collects:

   ```json
   {
     "deployment": "Deployment 2.5",
     "related_incidents": [],
     "runbook": "",
     "dependency_services": [],
     "recent_changes": []
   }
   ```

   In the local implementation, mockable connectors return runbooks, similar
   incidents, deployment data, CMDB dependencies, Kubernetes metadata, and
   Prometheus metrics.

5. `resolution-agent` runs this LangGraph workflow:

   ```text
   Collect Context -> Generate RCA -> Impact Analysis -> Generate Fix -> Confidence Scoring
   ```

   Example recommendation:

   ```json
   {
     "root_cause": "Deployment 2.5",
     "confidence": 0.91,
     "impact": "Payment latency",
     "recommended_action": "Rollback deployment"
   }
   ```

6. A human approves, rejects, or modifies using Slack, Teams, email, or Web UI:

   ```bash
   curl -X POST http://localhost:8007/approve \
     -H 'content-type: application/json' \
     -d '{"incident_id":"...","recommendation_id":"...","approver":"sre@example.com","channel":"web","comment":"Rollback deployment"}'
   ```

7. `remediation-engine` maps the decision to a Strategy plugin:

   - `JenkinsRollbackPlugin`
   - `KubernetesRestartPlugin`
   - `AnsibleRemediationPlugin`
   - `TerraformRollbackPlugin`
   - `ApiExecutionPlugin`

8. `closure-service` validates latency, CPU, error rate, and alert clearance,
   stores the RCA report, updates the knowledge base, and emits `closure-events`.

## Enterprise Engineering Features

- Pydantic event contracts
- AsyncIO-first Kafka, HTTP, and agent workflows
- SQLAlchemy async PostgreSQL persistence
- Redis-ready configuration
- Prometheus client metrics
- OpenTelemetry FastAPI tracing with optional OTLP exporter
- Structured JSON logging
- Retries and circuit breakers
- LangGraph RCA workflow
- LangChain-compatible deterministic embedding/RAG pattern
- Mockable vendor connectors and LLM providers
- Docker Compose local stack
- Kubernetes production manifests
- Unit and integration-style tests
