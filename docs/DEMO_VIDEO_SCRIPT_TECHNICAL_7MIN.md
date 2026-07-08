# KaiMS Technical Demo Video Script (7 Minutes)

Audience: SRE, platform, and engineering teams
Length: 7 minutes
Goal: Demonstrate end-to-end architecture and operational depth.

## 0:00 - 0:35 Architecture Context

On screen:
- README workflow section.
- Kafka handoff matrix section.

Voiceover:
- "This demo follows the full event path from raw-alerts through enrichment, orchestration, context collection, resolution, approval, remediation, and closure."

## 0:35 - 1:20 Alert Intake

On screen:
- Monitoring Adapter path and Alerts and Quick Docs tab.
- Load latest alerts.

Voiceover:
- "Alerts are ingested and published to raw-alerts. The UI shows a unified stream and quick guidance actions for runbook, incident history, and RCA context."

## 1:20 - 2:20 Agent Pipeline

On screen:
- Agent Flow tab.
- Expand role drill-down panels.

Voiceover:
- "Agent Flow exposes each role's action, input, output, and handoff. This preserves explainability and reduces hidden automation risk."

## 2:20 - 3:10 Guidance and RAG

On screen:
- Alerts and Quick Docs guidance area.
- Search guidance and open match previews.

Voiceover:
- "RAG-backed guidance is available during incident handling, helping operators map current symptoms to runbooks and known incidents in real time."

## 3:10 - 4:00 Approval and Policy

On screen:
- Approval state for a HIGH or CRITICAL path.
- Show approve or modify flow.

Voiceover:
- "Approval is policy-driven. High and critical severities require explicit human decision before continuation. This enforces governance while keeping lower-risk workflows fast."

## 4:00 - 4:50 Gateway Safety and Auditability

On screen:
- Gateway Safety tab with recent events and summary.

Voiceover:
- "Gateway safety checks and trace IDs provide full observability and policy audit records. You can inspect what was allowed, reviewed, or blocked."

## 4:50 - 5:40 FinOps and Model Telemetry

On screen:
- FinOps tab showing token and cost data.

Voiceover:
- "Model usage is transparent per task and provider, enabling optimization of cost, latency, and quality."

## 5:40 - 6:30 Closure and Learning Loop

On screen:
- Closed Incidents tab.
- Highlight closure validation and lessons learned.

Voiceover:
- "After remediation, closure is validated and retained as reusable operational knowledge, reducing repeat toil in future incidents."

## 6:30 - 7:00 Technical Close

On screen:
- Return to overview tabs.

Voiceover:
- "KaiMS combines event-driven architecture, governed automation, and operational visibility to deliver reliable incident response at scale."

## Suggested Demo Flow IDs

- database-replica-lag
- payment-latency
- redis-cache

## Recording Notes

- Record at 1080p, 30fps.
- Keep terminal popups minimized.
- Use a single run with one selected flow to avoid context switching.

