# KaiMS High-Level Design (HLD) v1.1 (Revised Draft)

## Document Control

| Item | Value |
|---|---|
| Project | KaiMS |
| Document | High-Level Design |
| Version | 1.1 |
| Status | Draft |
| Architecture Style | Event-Driven Microservices with Agentic Orchestration |
| Deployment | Containerized (Docker Compose for local, Kubernetes for production) |
| Primary Event Bus | Kafka |
| Compatibility Event Bus | RabbitMQ (selected workflows / migration compatibility) |
| Local Fallback | REST-only for local testing, not production-grade |
| Primary RDBMS | PostgreSQL |
| Compatible RDBMS | MySQL via repository abstraction |
| Cache | Redis |
| Knowledge Graph | Neo4j (phase-based rollout) |
| Vector Store | Qdrant |
| API Gateway | FastAPI-based gateway with policy controls |
| AI Workflow Runtime | LangGraph |
| Security Model | Zero Trust + Policy-Driven Automation |

## 1. Executive Summary
KaiMS is an enterprise agentic incident-resolution platform that automates the incident lifecycle from alert ingestion to closure and learning.

It combines event-driven microservices, specialized AI agents, governance controls, and human approval gates for high-risk actions.

The design prioritizes deterministic execution, auditability, explainability, and safe automation.

## 2. Problem Statement
Enterprise operations teams face:
1. High alert volume and alert fatigue
2. Duplicate alerts across monitoring tools
3. Manual and inconsistent RCA
4. Slow MTTR due to fragmented tooling
5. Limited automation with weak governance
6. Lack of explainability and immutable audit evidence

## 3. Business Objectives
KaiMS is designed to:
1. Reduce MTTR with automated context, RCA, and remediation support
2. Reduce alert noise via deduplication and correlation
3. Support two onboarding paths:
   - Existing monitoring path: ingest external alerts into landing pad
   - Setup monitoring path: generate rules from plain language and deploy to Prometheus
4. Enforce policy-driven automation with human-in-the-loop controls
5. Maintain immutable audit trails for compliance
6. Improve continuously from closed incidents and generated knowledge

## 4. Scope
### In Scope
1. Project onboarding and monitoring integration
2. Alert ingestion, enrichment, correlation, and routing
3. Agentic RCA and recommendation generation
4. Risk assessment and approval workflow
5. Remediation orchestration and validation
6. Knowledge generation (runbooks, troubleshooting docs, metadata)
7. Observability, audit, and operational reporting

### Out of Scope
1. Native implementation of third-party monitoring products
2. Full enterprise CMDB implementation
3. Enterprise ticketing implementation (integrations only)
4. Underlying infra procurement/provisioning standards

## 5. Normative Baseline (v1.1)
This section is authoritative for implementation decisions.

1. Production messaging: Kafka is primary; RabbitMQ is compatibility-path where already integrated; REST is local fallback only.
2. Data persistence: PostgreSQL primary; MySQL supported through data-access abstraction.
3. Security boundary: all side-effecting agent actions must pass policy evaluation and emit audit events.
4. Tenancy model: tenant-scoped identity, storage partitioning, and event namespace isolation.
5. Human approval required for high-risk and production-impacting actions.

## 6. Architecture Principles
1. Event-first architecture with durable replayable streams
2. Domain-driven service boundaries
3. Stateless services with stateful workflows
4. Deterministic execution contracts for retries/idempotency
5. Zero Trust and least privilege by default
6. Explainability and immutable auditability
7. Cloud-agnostic deployment profile
8. Observability by default

## 7. Logical Architecture Layers
1. Experience Layer
2. API and Security Layer
3. Messaging Layer
4. Agent Runtime Layer
5. AI Services Layer
6. Monitoring Adapter Layer
7. Data Layer
8. Automation Layer
9. Governance Layer
10. Observability Layer

## 8. Major Components
### Experience Layer
1. React dashboard and role-based consoles
2. Admin center for project onboarding and rule lifecycle
3. Approval portal and knowledge portal

### API and Security Layer
1. OAuth2/OIDC and JWT validation
2. Request validation and versioning
3. Rate limiting, audit logging, prompt sanitization
4. Policy enforcement point for action authorization

### Messaging Layer
Topics:
- raw-alerts
- enriched-alerts
- orchestration-events
- context-events
- resolution-events
- approval-events
- remediation-events
- validation-events
- closure-events
- learning-events
- audit-events

Required controls:
1. Idempotency keys
2. Retry policy
3. DLQ routing
4. Replay support

### Agent Runtime Layer
1. Onboarding Agent
2. Rule Generation Agent
3. Alert Intelligence Agent
4. Context Intelligence Agent
5. RCA Agent
6. Resolution Agent
7. Risk Assessment Agent
8. Approval Agent
9. Validation Agent
10. Learning Agent

### AI Services Layer
1. Model router and prompt registry
2. Tool registry and memory service
3. RAG engine and embedding service
4. Context builder and reflection engine

### Monitoring Adapter Layer
1. Prometheus (MVP baseline)
2. Datadog / Dynatrace / New Relic (phased)

Capabilities:
1. Connection management
2. Metric discovery
3. Rule generation
4. Validation/simulation
5. Deploy/rollback

### Data Layer
1. PostgreSQL: projects, users, incidents, workflows, approvals, audit logs
2. Neo4j (phased): service dependencies, impact graph, RCA paths
3. Qdrant: runbooks, SOPs, prior incidents, resolution knowledge
4. Redis: cache/session/short-lived workflow state

## 9. Deterministic Workflow Contract
Each event must define:
1. Producer service and owning domain
2. Consumer service(s)
3. Idempotency key strategy
4. Retry policy and max attempts
5. DLQ topic and replay procedure
6. Timeout budget and terminal state

For all side-effecting actions:
1. Policy check must execute before dispatch
2. Approval decision must be linked to action trace
3. Audit event must be immutable and queryable

## 10. Security Architecture (Implementable Controls)
### Identity and Access
1. OAuth2/OIDC SSO support
2. RBAC + ABAC policies
3. MFA and service-to-service auth

### AI Safety Controls
1. Prompt firewall and input sanitization
2. Output validation and policy scoring
3. Hallucination/jailbreak risk checks for high-risk operations

### Data Protection
1. TLS 1.3 in transit
2. AES-256 at rest
3. Secret manager integration
4. PII masking and DLP policies

### Compliance Evidence
1. Immutable audit logs
2. Traceable decision chain (input, policy result, output)
3. Retention and export controls aligned to SOC2/ISO27001/GDPR baseline

## 11. Multi-Tenancy and Isolation
1. Tenant ID mandatory on all business records
2. Topic namespace partition by tenant/domain
3. Vector and graph namespace isolation
4. Tenant-aware policy enforcement and rate limiting
5. Tenant-scoped audit views

## 12. Deployment Architecture
### Local Development
1. Docker Compose
2. Single-node Kafka/Postgres/Redis/Qdrant (minimal profile)
3. REST fallback only for local test scenarios

### Production
1. Kubernetes
2. Kafka cluster (durable stream backbone)
3. PostgreSQL HA
4. Redis HA
5. Neo4j and Qdrant clusters (as enabled by phase)
6. Prometheus + Grafana + Loki + Tempo/OpenTelemetry

## 13. End-to-End Workflows
### A. Existing Monitoring Path
1. Project configured with monitoring endpoint details
2. Alerts ingested to landing pad endpoint
3. Alert intelligence and orchestration pipeline triggered
4. RCA, risk, approval, remediation, validation, closure
5. Knowledge update and audit completion

### B. Setup Monitoring Path
1. Project onboarding completed
2. Plain-language rule intent captured
3. Rules generated and validated
4. Prometheus upload/reload/test attempted
5. Alerts flow into landing pad and trigger same runtime pipeline
6. Knowledge docs generated and approval-governed

## 14. Non-Functional Requirements (Measurable)

| Category | Requirement |
|---|---|
| Availability | 99.9% platform uptime |
| API Latency | p95 < 2s for operational APIs, p99 < 5s |
| AI Recommendation | p95 < 5s for standard incident context |
| Event Reliability | At-least-once + idempotent consumers |
| DLQ Recovery | Recovery SLA <= 30 minutes |
| DR | RTO <= 60 minutes, RPO <= 15 minutes |
| Scalability | Horizontal scale for stateless services |
| Auditability | Immutable logs for all policy and action decisions |
| Security | Zero Trust controls enforced at gateway and service boundaries |

## 15. Risks and Mitigations
1. LLM hallucination: RAG grounding, output validation, approval gates
2. Prompt injection: prompt firewall, model armor policies
3. Alert storms: Kafka buffering, backpressure, dedup/correlation
4. Unauthorized automation: policy engine + RBAC/ABAC + approval enforcement
5. Incorrect remediation: validation and rollback workflow
6. Data leakage: DLP, masking, encryption, tenant isolation

## 16. Roadmap
### MVP-1
1. Project onboarding
2. Prometheus integration
3. Existing monitoring ingestion path
4. Setup monitoring path with rule generation
5. Approval workflow and knowledge generation
6. Incident orchestration E2E

### MVP-2
1. Datadog/Dynatrace/New Relic adapters
2. Expanded autonomous remediation with stronger guardrails
3. CMDB and ticketing integrations
4. Graph-based dependency reasoning at scale
5. Predictive incident detection and operator copilot enhancements

## 17. Architecture Decisions Summary
1. Event-driven architecture for resilience and burst handling
2. Hub-and-spoke agent orchestration for controlled autonomy
3. Kafka-first production bus with compatibility adapters
4. LangGraph for stateful agent workflow control
5. PostgreSQL baseline with adapter portability
6. Policy-driven automation with mandatory audit trail
7. Human-in-the-loop for high-risk actions
8. Pluggable monitoring adapters for extensibility
