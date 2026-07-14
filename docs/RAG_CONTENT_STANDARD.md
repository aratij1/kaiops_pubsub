# RAG Content Standard (KaiMS)

## Purpose
This standard defines what should be stored in the RAG corpus, what should stay in source systems, and how to keep both synchronized.

## Decision Rule
Use this quick rule for any new content:

1. If it is procedural, explanatory, or historical knowledge, store in RAG.
2. If it is real-time, transactional, or governance-critical operational state, keep in source systems.
3. If both are needed, keep the canonical record in the source system and publish a curated summary to RAG.

## Where Each Content Type Belongs

| Content Type | Canonical Source | RAG Copy Needed | Notes |
| --- | --- | --- | --- |
| Runbooks | RAG markdown | Yes | Primary knowledge for guided remediation |
| SOPs | RAG markdown | Yes | Keep step-by-step instructions concise and explicit |
| Incident Postmortems | ITSM + RAG summary | Yes | Store final lessons and remediation guidance in RAG |
| Change Records | Change system (ServiceNow/Jira/Git) | Yes (summary) | Do not store raw audit trails in RAG |
| Dependency Graph | CMDB/service graph | Optional summary | Keep live topology outside RAG |
| Real-time Metrics | Prometheus/APM/logs | No | Query observability systems directly |
| Approval State | Approval service/DB | No | RAG can store policy guidance, not live state |
| Secrets/Credentials | Secret manager | No | Never in RAG |

## Required Folder Usage

- backend/rag/runbooks: procedural runbooks and SOPs
- backend/rag/incidents: incident knowledge entries and post-incident summaries
- backend/rag/changes: curated change summaries with operational impact
- backend/rag/dependencies: human-readable dependency narratives (not canonical graph)

## Required Metadata By Folder
The context-agent parser reads key-value metadata lines at the top of each markdown file, followed by a blank line.

Example parser-friendly structure:

kind: runbook
title: Payments latency rollback
services: payments, checkout
owner_team: platform-ops
last_reviewed: 2026-07-08
source_system: internal
source_ref: RUNBOOK-1024

# Payments latency rollback

...

### runbooks template
Required keys:
- kind: runbook
- title
- services
- owner_team
- last_reviewed
- source_system
- source_ref

### incidents template
Required keys:
- alert_id
- alert_name
- service
- severity
- alert_type
Optional keys:
- source_system
- source_ref
- resolved_by
- closed_at

### changes template
Required keys:
- kind: change
- title
- services
- deployment
- change_id
Optional keys:
- source_system
- source_ref
- risk_level
- rollout_window

### dependencies template
Required keys:
- kind: dependency
- title
- services
- dependencies
Optional keys:
- source_system
- source_ref
- last_reviewed

## Sync Standard (Source System -> RAG)

1. Incident close:
- Create or update a single incident knowledge markdown in backend/rag/incidents.
- Include root cause, impact, validated remediation, and prevention notes.

2. Approved change:
- Create/update summary in backend/rag/changes.
- Include operational blast radius and rollback signal.

3. Runbook/SOP update:
- Update markdown in backend/rag/runbooks.
- Update last_reviewed metadata.

4. Dependency review:
- Refresh narrative docs in backend/rag/dependencies after major architecture changes.

5. Reload index:
- Trigger POST /rag/reload after batch updates.

## Data Quality Rules

1. Keep each document single-purpose and under reasonable size.
2. Prefer concrete steps, thresholds, and commands over generic prose.
3. Remove stale references and outdated commands promptly.
4. Avoid duplicate documents for the same incident/change id.
5. No secrets, tokens, private keys, or credentials.

## Retention Guidance

1. Runbooks/SOPs: keep latest, update in place.
2. Incidents: keep at least 12 months of high-value incidents.
3. Changes: keep at least 6 months for active services.
4. Dependencies: review quarterly or after major platform changes.

## Ownership

1. SRE/Platform team owns runbooks, SOPs, and dependency docs.
2. Incident manager owns incident summaries.
3. Release/change owner owns change summaries.
4. AI platform owner validates metadata schema compliance.

## Current Implementation Notes

1. RAG documents are loaded from the rag folder by the context-agent vector connector.
2. Context fusion uses both connector data (CMDB/Prometheus/Jenkins/etc.) and RAG matches.
3. RAG should remain a knowledge layer, not a runtime state store.

## Templates

Use the following templates for new documents:

1. Runbook template: [docs/rag-templates/runbook.template.md](docs/rag-templates/runbook.template.md)
2. Incident template: [docs/rag-templates/incident.template.md](docs/rag-templates/incident.template.md)
3. Change template: [docs/rag-templates/change.template.md](docs/rag-templates/change.template.md)
4. Dependency template: [docs/rag-templates/dependency.template.md](docs/rag-templates/dependency.template.md)
5. Deployment template: [docs/rag-templates/deployment.template.md](docs/rag-templates/deployment.template.md)
6. SOP template: [docs/rag-templates/sop.template.md](docs/rag-templates/sop.template.md)
7. Onboarding template: [docs/rag-templates/onboarding.template.md](docs/rag-templates/onboarding.template.md)

## Validation Tooling

Validate the corpus metadata before merge:

1. Standard mode (fails on errors only):
python scripts/validate-rag-metadata.py --rag-root rag
2. Strict mode (fails on warnings too):
python scripts/validate-rag-metadata.py --rag-root rag --strict
