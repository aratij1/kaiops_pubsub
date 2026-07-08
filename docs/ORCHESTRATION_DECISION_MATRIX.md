# KaiMS Orchestration Decision Matrix

This page explains how KaiMS decides how to troubleshoot and process incidents/alerts using:
- policy rules
- deterministic workflow routing
- optional LLM planner
- RAG-grounded context and resolution logic

## Effective Policy Defaults

From service settings:
- ORCHESTRATION_APPROVAL_SEVERITIES: high,critical
- CONFIDENCE_GUIDED_EXECUTE_THRESHOLD: 0.75
- CONFIDENCE_AUTO_EXECUTE_THRESHOLD: 0.90
- ORCHESTRATION_LLM_PLANNER_ENABLED: false
- ALERT_CORRELATION_THRESHOLD: 0.72
- MESSAGE_BUS_DYNAMIC_ROUTING: true
- MESSAGE_BUS_STREAM_THRESHOLD: 500
- MESSAGE_BUS_DEFAULT_PROVIDER: rabbitmq

## Severity to Risk Tier

| Alert Severity | Risk Tier |
| --- | --- |
| CRITICAL | high |
| HIGH | high |
| WARNING | medium |
| INFO | low |

## Policy Decision Rules

Evaluation order:
1. If severity is in mandatory approval set (high, critical), require human approval.
2. Else if confidence is missing, use guided-auto.
3. Else compare confidence to thresholds:
   - confidence < 0.75 -> human-approval
   - 0.75 <= confidence < 0.90 -> guided-auto
   - confidence >= 0.90 -> auto-execute

## Workflow Selection (Deterministic Base)

| Severity | Base Workflow | Typical Path |
| --- | --- | --- |
| CRITICAL | critical-auto-remediation | Full flow, approval gate still enforced by policy |
| HIGH | guided-remediation | Guided remediation with approval when required |
| WARNING / INFO | triage-only | Triage, RCA, notification-focused handling |

Notes:
- Optional LLM planner may propose one of the same three workflows if enabled.
- If planner fails or gives unsupported output, KaiMS falls back to deterministic severity routing.

## One-Page Decision Matrix

| Severity | Confidence | Requires Approval | Execution Mode | Workflow |
| --- | --- | --- | --- | --- |
| CRITICAL | any | true | human-approval | critical-auto-remediation |
| HIGH | any | true | human-approval | guided-remediation |
| WARNING | missing | false | guided-auto | triage-only |
| WARNING | < 0.75 | true | human-approval | triage-only |
| WARNING | 0.75 to < 0.90 | false | guided-auto | triage-only |
| WARNING | >= 0.90 | false | auto-execute | triage-only |
| INFO | missing | false | guided-auto | triage-only |
| INFO | < 0.75 | true | human-approval | triage-only |
| INFO | 0.75 to < 0.90 | false | guided-auto | triage-only |
| INFO | >= 0.90 | false | auto-execute | triage-only |

## Message Bus Routing Rule

When MESSAGE_BUS_DYNAMIC_ROUTING is true:
- stream_count > 500 -> kafka
- stream_count <= 500 -> rabbitmq

When dynamic routing is false:
- use MESSAGE_BUS_DEFAULT_PROVIDER

## Where Policy, Rules, and RAG Interact

1. Alert Intelligence:
   - deduplicates and correlates alerts
   - classifies severity and enriches metadata
2. Orchestrator + Policy Engine:
   - computes risk tier, approval requirement, execution mode, workflow
3. Context Agent (RAG + connectors):
   - retrieves runbooks/incidents/dependencies/changes/deployments
   - builds grounded context for troubleshooting
4. Resolution Agent:
   - generates root cause, impact, remediation action, confidence
5. Approval and Remediation:
   - executes according to policy decision and workflow state

## Troubleshooting Decision Explainability Fields

For each decision/event, KaiMS emits decision metadata such as:
- policy_version
- policy_reason
- risk_tier
- execution_mode
- requires_approval
- workflow
- planner_used
- planner_reason
- message_bus_provider

These fields are persisted and shown in API/UI views for auditability.
