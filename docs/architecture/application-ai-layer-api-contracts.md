# KaiOps Application Layer To AI Layer API Contracts

This document shows how the application layer talks to the AI layer. In production, the UI and application services should call the AI layer only through configured HTTP endpoints or message-bus topics. The application layer should not import AI code directly.

## Runtime Boundaries

Application layer:
- UI / Admin Cockpit
- API Gateway
- Monitoring Adapter / Landing Pad
- Orchestrator
- Approval Service
- Remediation Engine
- Application Onboarding
- Reports and dashboards

AI layer:
- Context Agent
- Resolution Agent
- Model Router
- Knowledge Router / Vector RAG index
- Evaluation service
- Embedding provider
- LLM providers

## API Gateway Routing

All browser and application-layer callers should use the API Gateway:

```text
UI / Application Service
  -> POST /api-gateway/knowledge-pack/draft
  -> API Gateway safety/auth/audit
  -> Context Agent /knowledge-pack/draft
```

Gateway response shape is wrapped by `guarded_proxy`:

```json
{
  "data": {},
  "event_contract": {
    "agent": "api-gateway",
    "trace_id": "trace-123",
    "confidence": 1.0
  },
  "safety": {
    "decision": "allow",
    "score": 0.0,
    "categories": [],
    "reasons": [],
    "provider": "local"
  }
}
```

## 1. Draft Service Knowledge

Used by Admin Setup after the user enters a prompt or uploads a source document.

Request:

```http
POST /api-gateway/knowledge-pack/draft
Content-Type: application/json
X-Trace-Id: setup-trace-001
```

```json
{
  "service": "mysql-exporter",
  "environment": "prod",
  "owner_team": "data-platform",
  "documents": [
    {
      "name": "mysql-exporter-knowledge.md",
      "category": "knowledge_pack",
      "text": "Service: mysql-exporter\nOwner team: data-platform\nAlert when exporter is unavailable for 5 minutes. Validate Prometheus metrics, MySQL connectivity, exporter health and row-count query. Rollback by restoring previous exporter config and restarting exporter.",
      "excerpt": "Prometheus and MySQL exporter availability baseline."
    }
  ]
}
```

AI layer target:

```text
Context Agent: POST /knowledge-pack/draft
```

Response:

```json
{
  "data": {
    "status": "drafted",
    "knowledge_pack": {
      "contract_version": "kaiops.knowledge-pack.v1",
      "status": "ready",
      "document_count": 1,
      "facts": {
        "service": {
          "value": "mysql-exporter",
          "confidence": 0.96,
          "sources": ["mysql-exporter-knowledge.md"],
          "status": "accepted"
        },
        "environment": {
          "value": "prod",
          "confidence": 0.92,
          "sources": ["mysql-exporter-knowledge.md"],
          "status": "accepted"
        },
        "owner_team": {
          "value": "data-platform",
          "confidence": 0.92,
          "sources": ["mysql-exporter-knowledge.md"],
          "status": "accepted"
        },
        "alert_patterns": {
          "value": ["when exporter is unavailable for 5 minutes"],
          "confidence": 0.84,
          "sources": ["mysql-exporter-knowledge.md"],
          "status": "accepted"
        }
      },
      "validation": {
        "missing_required": [],
        "missing_recommended": ["commands"],
        "low_confidence": [],
        "overall_confidence": 0.81
      },
      "next_questions": []
    }
  }
}
```

## 2. Validate Service Knowledge

Used when the UI needs the AI layer to re-score corrected details before approval.

Request:

```http
POST /api-gateway/knowledge-pack/validate
Content-Type: application/json
X-Trace-Id: setup-trace-002
```

```json
{
  "service": "mysql-exporter",
  "environment": "prod",
  "owner_team": "data-platform",
  "documents": [
    {
      "name": "mysql-exporter-knowledge.md",
      "category": "knowledge_pack",
      "text": "Alert when mysql-exporter is down for 5m. Dependencies: MySQL, Prometheus, Grafana. Rollback: restore previous exporter config and restart exporter."
    }
  ]
}
```

Response:

```json
{
  "data": {
    "status": "ready",
    "knowledge_pack": {
      "status": "ready",
      "facts": {
        "service": {"value": "mysql-exporter", "confidence": 0.96, "status": "accepted"},
        "dependencies": {"value": ["MySQL", "Prometheus", "Grafana"], "confidence": 0.82, "status": "accepted"},
        "rollback_plan": {"value": ["restore previous exporter config and restart exporter"], "confidence": 0.78, "status": "accepted"}
      }
    },
    "validation": {
      "missing_required": [],
      "missing_recommended": ["commands", "validation_checks"],
      "low_confidence": [],
      "overall_confidence": 0.78
    },
    "next_questions": [
      "How should KaiOps verify recovery after remediation?"
    ]
  }
}
```

## 3. Approve Knowledge Pack And Write RAG Document

Used after a user has corrected the editable table and approves the knowledge.

Request:

```http
POST /api-gateway/knowledge-pack/approve
Content-Type: application/json
X-Trace-Id: setup-trace-003
```

```json
{
  "service": "mysql-exporter",
  "environment": "prod",
  "owner_team": "data-platform",
  "accepted_facts": {
    "service": "mysql-exporter",
    "environment": "prod",
    "owner_team": "data-platform",
    "dependencies": ["MySQL", "Prometheus", "Grafana"],
    "alert_patterns": ["critical alert when exporter is down for 5 minutes"],
    "commands": ["bash scripts/remediation/kaiops_alert_health_triage.sh --service mysql-exporter --environment prod --prometheus-url http://prometheus:9090 --mysql-host mysql --dry-run true"],
    "rollback_plan": ["restore previous exporter config and restart exporter"],
    "validation_checks": ["Prometheus target up", "mysql-exporter /metrics available", "row-count query succeeds"]
  },
  "approved_by": "admin",
  "documents": [
    {
      "name": "mysql-exporter-knowledge.md",
      "category": "knowledge_pack",
      "text": "Approved MySQL exporter monitoring and remediation knowledge."
    }
  ]
}
```

Response:

```json
{
  "data": {
    "status": "approved",
    "knowledge_pack": {
      "status": "approved",
      "facts": {
        "service": {"value": "mysql-exporter", "confidence": 0.96, "status": "accepted"},
        "commands": {"value": ["bash scripts/remediation/kaiops_alert_health_triage.sh --service mysql-exporter --environment prod --prometheus-url http://prometheus:9090 --mysql-host mysql --dry-run true"], "confidence": 0.9, "status": "accepted"}
      }
    },
    "rag_document": {
      "kind": "runbook",
      "path": "/app/rag/runbooks/mysql-exporter-knowledge-pack.md",
      "title": "mysql-exporter Knowledge Pack"
    }
  }
}
```

## 4. Direct RAG Document Ingestion

Used by onboarding, rule generation, or alert documents when a structured document is already available.

Request:

```http
POST /api-gateway/rag/documents
Content-Type: application/json
X-Trace-Id: rag-trace-001
```

```json
{
  "kind": "runbook",
  "alert_id": "alert-123",
  "alert_type": "KaiOpsMySQLAlertsTableRowsHigh",
  "severity": "critical",
  "title": "MySQL table rows high runbook",
  "summary": "Investigate abnormal MySQL row growth.",
  "content": "Check ingestion rate, row count deltas, ETL job status, and table partitioning.",
  "services": ["mysql", "etl-orders"],
  "dependencies": ["Prometheus", "MySQL"],
  "commands": [],
  "scripts": [
    "bash scripts/remediation/kaiops_alert_health_triage.sh --service mysql --environment prod --prometheus-url http://prometheus:9090 --mysql-host mysql --dry-run true"
  ],
  "queries": ["SELECT COUNT(*) FROM alerts;"],
  "metadata": {
    "environment": "prod",
    "prometheus_url": "http://prometheus:9090",
    "mysql_host": "mysql",
    "mysql_database": "kaiops",
    "mysql_user": "kaiops"
  }
}
```

Response:

```json
{
  "data": {
    "status": "ingested",
    "document_flag_updated": true,
    "kind": "runbook",
    "path": "/app/rag/runbooks/mysql-table-rows-high-runbook.md",
    "title": "MySQL table rows high runbook"
  }
}
```

## 5. RAG Index And Search

Used by UI Context Flow and by agents to show which documents were touched.

Request:

```http
POST /api-gateway/rag/reload
X-Trace-Id: rag-trace-002
```

Response:

```json
{
  "data": {
    "status": "reloaded",
    "document_count": 42,
    "index": {
      "embedding_provider": "openai",
      "embedding_model": "text-embedding-3-large",
      "vector_store": "qdrant",
      "vector_index": "kaiops-rag-prod",
      "documents_seen": 42
    }
  }
}
```

Search request:

```http
GET /api-gateway/rag/search?query=mysql-exporter%20down%20prod&limit=5
X-Trace-Id: rag-trace-003
```

Response:

```json
{
  "data": {
    "query": "mysql-exporter down prod",
    "index": {
      "embedding_provider": "openai",
      "embedding_model": "text-embedding-3-large",
      "vector_store": "qdrant"
    },
    "matches": [
      {
        "kind": "runbook",
        "title": "mysql-exporter Knowledge Pack",
        "services": ["mysql-exporter"],
        "path": "/app/rag/runbooks/mysql-exporter-knowledge-pack.md",
        "score": 0.91,
        "preview": "Validate Prometheus target up, exporter /metrics and MySQL connectivity..."
      }
    ]
  }
}
```

## 6. Context Collection

Normally event-driven from `orchestration-events`. This synchronous endpoint is useful for tests and controlled replays.

Request:

```http
POST /context-agent/collect
Content-Type: application/json
```

```json
{
  "alert": {
    "id": "79ac836d-2d50-49eb-b8da-74b938a0c476",
    "source": "prometheus",
    "name": "KaiOpsMySQLAlertsTableRowsHigh",
    "service": "mysql",
    "environment": "prod",
    "severity": "critical",
    "description": "MySQL table rows are above threshold.",
    "labels": {"job": "mysql-exporter"},
    "annotations": {"summary": "MySQL table rows high"}
  },
  "incident": {
    "id": "f1b3df97-2604-4df2-9a31-d3f866bb4871",
    "alert_ids": ["79ac836d-2d50-49eb-b8da-74b938a0c476"],
    "service": "mysql",
    "environment": "prod",
    "severity": "critical",
    "status": "investigating",
    "title": "MySQL table rows high"
  },
  "decision": {
    "workflow": "critical-auto-remediation",
    "requires_approval": true,
    "message_bus_provider": "rabbitmq",
    "policy_version": "policy-v1"
  }
}
```

Response:

```json
{
  "id": "a54a5e1d-64cb-44bb-9844-cba6b2dfef1c",
  "incident_id": "f1b3df97-2604-4df2-9a31-d3f866bb4871",
  "alert": {
    "name": "KaiOpsMySQLAlertsTableRowsHigh",
    "service": "mysql",
    "severity": "critical"
  },
  "deployment": "prod",
  "related_incidents": [],
  "runbook": "mysql-exporter Knowledge Pack",
  "dependency_services": ["Prometheus", "MySQL"],
  "recent_changes": [],
  "cmdb": {},
  "cloud": {},
  "kubernetes": {},
  "observability": {},
  "metadata": {
    "rag_documents": 42,
    "rag_matches": [{"title": "mysql-exporter Knowledge Pack", "score": 0.91}],
    "rag_top_similarity": 0.91,
    "rag_service_tagged_match": true
  }
}
```

Published event:

```text
context-agent -> context-events
```

```json
{
  "context": {},
  "incident": {},
  "decision": {},
  "transport": "rabbitmq",
  "event_contract": {
    "agent": "context-agent",
    "topic": "context-events",
    "trace_id": "setup-trace-003",
    "confidence": 0.84,
    "citations": ["alert://79ac836d-2d50-49eb-b8da-74b938a0c476"],
    "evidence_ids": ["alert:79ac836d-2d50-49eb-b8da-74b938a0c476", "incident:f1b3df97-2604-4df2-9a31-d3f866bb4871"]
  }
}
```

## 7. Resolution Generation

Normally event-driven from `context-events`. Direct endpoint is used for smoke tests and replay.

Request:

```http
POST /resolution-agent/resolve
Content-Type: application/json
```

```json
{
  "incident_id": "f1b3df97-2604-4df2-9a31-d3f866bb4871",
  "alert": {
    "source": "prometheus",
    "name": "KaiOpsMySQLAlertsTableRowsHigh",
    "service": "mysql",
    "environment": "prod",
    "severity": "critical",
    "description": "MySQL table rows are above threshold."
  },
  "deployment": "prod",
  "runbook": "mysql-exporter Knowledge Pack",
  "dependency_services": ["Prometheus", "MySQL"],
  "metadata": {
    "rag_documents": 42,
    "rag_matches": [{"title": "mysql-exporter Knowledge Pack", "score": 0.91}],
    "rag_top_similarity": 0.91,
    "rag_service_tagged_match": true
  }
}
```

Response:

```json
{
  "id": "396b4f10-63de-47d4-b457-e83637157cf0",
  "incident_id": "f1b3df97-2604-4df2-9a31-d3f866bb4871",
  "root_cause": "MySQL table growth exceeded the configured threshold.",
  "confidence": 0.86,
  "impact": "Storage, ETL latency, and dashboard freshness can be affected.",
  "recommended_action": "Run dry-run triage, validate row growth source, confirm Prometheus target health, then apply approved remediation.",
  "severity": "critical",
  "rationale": "Matched mysql-exporter knowledge pack and current alert labels.",
  "commands": [
    "bash scripts/remediation/kaiops_alert_health_triage.sh --service mysql --environment prod --prometheus-url http://prometheus:9090 --mysql-host mysql --dry-run true"
  ],
  "risk": "medium",
  "metadata": {
    "rag_documents": 42,
    "rag_top_similarity": 0.91,
    "runbook_found": true,
    "evaluation": {
      "confidence_score": 0.86,
      "grounding_score": 0.91,
      "hallucination_risk": 0.09,
      "citation_quality": 0.88
    }
  }
}
```

Published event:

```text
resolution-agent -> resolution-events
```

```json
{
  "recommendation": {},
  "context": {},
  "incident": {},
  "decision": {},
  "event_contract": {
    "agent": "resolution-agent",
    "topic": "resolution-events",
    "confidence": 0.86,
    "evidence_ids": ["alert:79ac836d-2d50-49eb-b8da-74b938a0c476"]
  }
}
```

## 8. Model Router

Used by AI agents when they need LLM generation. Application layer can call this only through API Gateway for diagnostics.

Request:

```http
POST /api-gateway/model/route
Content-Type: application/json
X-Trace-Id: model-trace-001
```

```json
{
  "task": "resolution_rca",
  "prompt": "Use the supplied evidence to produce root cause and remediation.",
  "context": {
    "service": "mysql",
    "alert": "KaiOpsMySQLAlertsTableRowsHigh",
    "evidence": ["mysql-exporter Knowledge Pack", "Prometheus target up"]
  },
  "constraints": {
    "require_json": true,
    "max_tokens": 900,
    "allow_fallback": true
  }
}
```

Response:

```json
{
  "data": {
    "provider": "gemini",
    "model": "gemini-2.0-flash",
    "fallback_used": false,
    "text": "{\"root_cause\":\"...\",\"recommended_action\":\"...\"}",
    "usage": {
      "input_tokens": 640,
      "output_tokens": 220,
      "estimated_cost": 0.0
    },
    "latency_ms": 1210
  }
}
```

## 9. Approval And Remediation Handoff

Approval stays in the application layer, but it consumes AI-generated recommendation IDs.

Approval request:

```http
POST /api-gateway/approval/approve
Content-Type: application/json
X-Trace-Id: approval-trace-001
```

```json
{
  "incident_id": "f1b3df97-2604-4df2-9a31-d3f866bb4871",
  "recommendation_id": "396b4f10-63de-47d4-b457-e83637157cf0",
  "approver": "l2.engineer",
  "channel": "web",
  "comment": "Approved after dry-run review."
}
```

Response:

```json
{
  "data": {
    "id": "6a4c31a7-3701-44ea-a710-efb7c7c983e1",
    "incident_id": "f1b3df97-2604-4df2-9a31-d3f866bb4871",
    "recommendation_id": "396b4f10-63de-47d4-b457-e83637157cf0",
    "decision": "approved",
    "approver": "l2.engineer",
    "channel": "web",
    "comment": "Approved after dry-run review."
  }
}
```

Remediation request:

```http
POST /api-gateway/remediation/execute
Content-Type: application/json
X-Trace-Id: remediation-trace-001
```

```json
{
  "approval": {
    "id": "6a4c31a7-3701-44ea-a710-efb7c7c983e1",
    "incident_id": "f1b3df97-2604-4df2-9a31-d3f866bb4871",
    "recommendation_id": "396b4f10-63de-47d4-b457-e83637157cf0",
    "decision": "approved"
  },
  "recommendation": {
    "id": "396b4f10-63de-47d4-b457-e83637157cf0",
    "incident_id": "f1b3df97-2604-4df2-9a31-d3f866bb4871",
    "recommended_action": "Run mysql alert health triage.",
    "commands": [
      "bash scripts/remediation/kaiops_alert_health_triage.sh --service mysql --environment prod --prometheus-url http://prometheus:9090 --mysql-host mysql --dry-run true"
    ],
    "metadata": {
      "service": "mysql",
      "environment": "prod",
      "remediation_target": "mysql"
    }
  }
}
```

Response:

```json
{
  "data": {
    "id": "2f85fa87-d9bd-4d38-bd5a-f58382fb92d1",
    "incident_id": "f1b3df97-2604-4df2-9a31-d3f866bb4871",
    "approval_id": "6a4c31a7-3701-44ea-a710-efb7c7c983e1",
    "action_type": "script",
    "target": "mysql",
    "parameters": {
      "execution_mode": "dry_run",
      "service": "mysql",
      "environment": "prod"
    },
    "status": "succeeded",
    "output": "Dry run completed. Prometheus target checked. MySQL connectivity checked."
  }
}
```

## Event-Driven Flow Summary

```text
Monitoring Adapter / Landing Pad
  -> raw-alerts
  -> Alert Intelligence
  -> enriched-alerts
  -> Orchestrator
  -> orchestration-events
  -> Context Agent
  -> context-events
  -> Resolution Agent
  -> resolution-events
  -> Approval Service
  -> approval-events
  -> Remediation Engine
  -> remediation-events
  -> Closure / Notification
```

## Required Production Headers

```text
Authorization: Bearer <access-token>
Content-Type: application/json
X-Trace-Id: <tenant-service-incident-trace>
X-Tenant-Id: <tenant-id>
X-Correlation-Id: <source-alert-fingerprint>
```

## Operational Rules

- Application layer owns auth, RBAC, approval, remediation execution, ticket state, UI state, and API audit.
- AI layer owns context collection, RAG search, model routing, recommendation generation, scoring, and citations.
- Every AI response must return confidence, grounding/citation evidence, trace ID, and fallback metadata.
- Every remediation must include approval ID, recommendation ID, dry-run support, rollback plan, and post-checks.
- For scale, synchronous APIs should be used for UI actions; high-volume alert processing should use message bus topics.

## AI Layer Scalability

The AI layer must scale separately from the application layer. Application APIs are usually CPU, database, and request-latency bound. AI services are model-latency, token, embedding, vector-search, and provider-quota bound.

Recommended Azure production deployment:

```text
AI API / private endpoint
  -> Model Router replicas
  -> Context Agent worker pool
  -> Resolution Agent worker pool
  -> Embedding worker pool
  -> Reranker worker pool, optional GPU
  -> Evaluation worker pool
  -> Azure OpenAI / OpenAI / Gemini regional provider pools
```

Scale units:

```text
context-agent replicas      scale by orchestration-events queue depth and p95 collection latency
resolution-agent replicas   scale by context-events queue depth, model p95 latency, and active critical incidents
model-router replicas       scale by requests per second, provider retry backlog, and circuit-breaker open rate
embedding workers           scale by document ingestion backlog and embedding batch depth
rag/vector search           scale by vector query p95 latency, index size, and concurrent searches
evaluation workers          scale by resolution-events backlog and score-generation latency
```

KEDA/HPA triggers:

```yaml
ai_autoscaling:
  min_replicas: 2
  max_replicas: 20
  triggers:
    - azure_service_bus_queue: orchestration-events
      target_queue_length: 50
      target: context-agent
    - azure_service_bus_queue: context-events
      target_queue_length: 35
      target: resolution-agent
    - azure_service_bus_queue: embedding-jobs
      target_queue_length: 100
      target: embedding-workers
    - metric: model_router_p95_latency_ms
      threshold: 5000
      target: model-router
    - metric: llm_provider_throttle_rate
      threshold: 0.05
      target: model-router
    - metric: vector_search_p95_latency_ms
      threshold: 300
      target: rag-router
```

Provider quota controls:

```text
- split Azure OpenAI deployments by workload: rca, remediation, summarization, embeddings
- use regional fallback pools where data policy permits
- keep token budgets per tenant, environment, and severity
- use circuit breakers when provider 429/5xx rate crosses threshold
- fall back from premium model to fast model to deterministic non-LLM response
- queue low-severity resolution when critical incident backlog is high
```

AI layer state rules:

```text
- AI workers stay stateless
- prompts, model versions, and response evaluations are written to audit storage
- RAG documents live in object storage and vector DB, not local container disk
- idempotency keys are required for replayed context/resolution jobs
- all AI events carry trace_id, incident_id, alert_id, recommendation_id when available
```
