# Policy, Workflow, and AI Orchestrator Flow

This document describes how KaiMS makes orchestration decisions using:

- Policy Engine (authoritative risk and approval rules)
- Workflow Engine (workflow and bus routing)
- AI planner (optional advisory planner)
- Orchestrator Agent (final decision assembly)

## 1. Policy Engine Flow

Source: `backend/src/common/common/orchestration/policy_engine.py`

```mermaid
flowchart TD
  A[Input severity and confidence] --> B[Map severity to risk_tier]
  B --> C{Severity in approval_severities?}
  C -- Yes --> D[requires_approval=true\nexecution_mode=human-approval\nreason=mandatory severity]
  C -- No --> E{Confidence present?}
  E -- No --> F[requires_approval=false\nexecution_mode=guided-auto\nreason=no confidence]
  E -- Yes --> G{confidence < guided threshold?}
  G -- Yes --> H[requires_approval=true\nexecution_mode=human-approval\nreason=below guided threshold]
  G -- No --> I{confidence < auto threshold?}
  I -- Yes --> J[requires_approval=false\nexecution_mode=guided-auto\nreason=guided range]
  I -- No --> K[requires_approval=false\nexecution_mode=auto-execute\nreason=above auto threshold]
```

Outputs:

- `risk_tier`
- `requires_approval`
- `execution_mode`
- `reason`

## 2. Workflow Engine Flow

Source: `backend/src/common/common/orchestration/workflow_engine.py`

```mermaid
flowchart TD
  A[Input severity confidence stream_count] --> B[Deterministic workflow by severity]
  B --> C[critical -> critical-auto-remediation]
  B --> D[high -> guided-remediation]
  B --> E[warning/info -> triage-only]

  A --> F[Route message bus]
  F --> G{dynamic_routing enabled?}
  G -- No --> H[Use default_provider]
  G -- Yes --> I{stream_count > stream_threshold?}
  I -- Yes --> J[kafka]
  I -- No --> K[rabbitmq]

  A --> L[Evaluate policy engine]
  L --> M[risk_tier, requires_approval, execution_mode, reason]

  C --> N[Build WorkflowSelection]
  D --> N
  E --> N
  H --> N
  J --> N
  K --> N
  M --> N
```

`WorkflowSelection` contains:

- workflow definition (`name`, `steps`, `next_action`)
- policy outputs (`risk_tier`, `requires_approval`, `execution_mode`)
- message bus choice (`message_bus_provider`, `stream_count`, `stream_threshold`)

## 3. AI Planner Flow (Advisory)

Source: `WorkflowEngine.select_with_planner()` and `_plan_workflow_name()`

```mermaid
flowchart TD
  A[Base deterministic selection] --> B{ORCHESTRATION_LLM_PLANNER_ENABLED?}
  B -- No --> C[Return base selection]
  B -- Yes --> D[Call ModelRouter with planner prompt]
  D --> E{Planner output valid workflow?}
  E -- No --> F[Fallback to deterministic workflow\nplanner_used=false]
  E -- Yes --> G[Replace workflow definition only\nplanner_used=true]
  F --> H[Keep policy and approval from rules]
  G --> H
  H --> I[Return final WorkflowSelection]
```

Planner is advisory only. Policy remains authoritative.

## 4. AI Orchestrator Agent Flow

Source: `backend/src/orchestrator/orchestrator/workflow.py`

```mermaid
sequenceDiagram
  autonumber
  participant O as OrchestratorAgent
  participant AO as AgentOrchestrator
  participant WE as WorkflowEngine
  participant PE as PolicyEngine
  participant EP as ExecutionPlan Resolver

  O->>AO: select_async(alert, incident)
  AO->>WE: select_with_planner(severity, confidence, stream_count)
  WE->>PE: evaluate(severity, confidence)
  PE-->>WE: risk_tier, requires_approval, execution_mode, reason
  WE-->>AO: WorkflowSelection
  AO-->>O: WorkflowSelection
  O->>EP: resolve_execution_plan(alert, workflow_name, requires_approval, risk_tier, execution_mode)
  EP-->>O: connector + preflight + steps + commands
  O-->>Caller: WorkflowDecision
```

`WorkflowDecision` includes:

- `workflow`, `next_action`, `downstream_agents`
- `requires_approval`, `risk_tier`, `execution_mode`
- `policy_version`, `policy_reason`
- `planner_used`, `planner_model`, `planner_reason`
- `message_bus_provider`, `stream_count`, `stream_threshold`
- `execution_plan`

## 5. Combined End-to-End Decision Flow

```mermaid
flowchart LR
  A[Alert arrives with severity and context] --> B[Policy Engine evaluates risk and approval mode]
  A --> C[Workflow Engine chooses base workflow]
  A --> D[Workflow Engine selects bus route]
  C --> E{LLM planner enabled?}
  E -- Yes --> F[Planner proposes workflow]
  E -- No --> G[Keep deterministic workflow]
  F --> H[Validate planner output]
  H --> I[Use planner workflow or fallback]
  G --> I
  B --> J[Policy remains authoritative]
  D --> K[Message bus provider selected]
  I --> L[Orchestrator builds workflow decision]
  J --> L
  K --> L
  L --> M[Execution plan resolved from connectors actions and playbooks]
  M --> N[Context -> Resolution -> Approval -> Remediation -> Closure]
```

## 6. Guardrails and Guarantees

- Severity gates can force approval regardless of planner output.
- Invalid planner output never breaks flow; deterministic fallback is automatic.
- Policy metadata (`risk_tier`, `execution_mode`, `policy_reason`) is propagated in orchestration outputs.
- Execution plan is resolved after workflow selection using connector, action catalog, and playbook data.

## 7. Context Engine Flow

Sources:

- `backend/src/context-agent/app.py`
- `backend/src/context-agent/context_agent/connectors.py`

```mermaid
flowchart TD
  A[Consume orchestration-events] --> B[Validate alert and incident payload]
  B --> C[Collect context from connectors]
  C --> D[VectorDB RAG retrieval\nrunbooks incidents sops onboarding]
  C --> E[Operational context\ndependencies changes deployment signals]
  D --> F[Merge and shape context object]
  E --> F
  F --> G[Select transport provider\nkafka or rabbitmq]
  G --> H[Publish context-events]
  H --> I[Resolution agent consumes context]
```

```mermaid
sequenceDiagram
  autonumber
  participant OR as Orchestrator
  participant BUS as Message Bus
  participant CTX as Context Agent
  participant RAG as VectorDB Connector
  participant RES as Resolution Agent

  OR->>BUS: orchestration-events
  BUS->>CTX: consume event
  CTX->>CTX: model_validate(alert, incident)
  CTX->>RAG: collect relevant docs and evidence
  RAG-->>CTX: runbook/incident/dependency/deployment context
  CTX->>CTX: build Context object
  CTX->>BUS: context-events with decision + transport metadata
  BUS->>RES: context-events
```

### Context Engine Example

Example alert: `payments-webhook-retry-storm`

1. Orchestrator publishes `orchestration-events` with incident, alert, and decision metadata.
2. Context agent consumes the event and validates both payloads into `Alert` and `Incident` models.
3. Context collection retrieves RAG evidence for webhook retries, related incidents, and operational dependencies.
4. Context agent builds a consolidated `Context` object containing:
   - related incidents
   - dependency services
   - recent changes and deployment hints
   - runbook/SOP evidence
5. Context agent publishes `context-events` on the selected bus provider (kafka or rabbitmq).
6. Resolution agent consumes `context-events` and performs RCA and recommendation generation with grounded context.

### Runtime Notes

- Context agent receives orchestration events from both kafka and rabbitmq workers when enabled.
- Outbound context event transport is selected from decision metadata with a rabbitmq fallback.
- Context publishing includes decision and transport markers used downstream for explainability.
