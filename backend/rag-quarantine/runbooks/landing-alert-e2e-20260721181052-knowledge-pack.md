kind: runbook
title: landing-alert-e2e-20260721181052 Knowledge Pack
services: landing-alert-e2e-20260721181052
dependencies: prometheus, alertmanager, landing-pad, rabbitmq, context-agent, resolution-agent, approval-service, remediation-engine
source_system: knowledge-pack
resolved_by: platform-ops
environment: prod
knowledge_pack_status: approved
knowledge_pack_confidence: 0.855

# landing-alert-e2e-20260721181052 Knowledge Pack

## Summary
Approved KaiOps knowledge pack for landing-alert-e2e-20260721181052.

## Description
Knowledge pack for landing-alert-e2e-20260721181052 in prod.

Alert patterns:
- e2e-20260721181052-api-gateway-highrequestlatency-knowledge.md
- HighRequestLatency
- e2e-20260721181052-api-gateway-kaiopshighlatencyp95-knowledge.md
- KaiOpsHighLatencyP95
- e2e-20260721181052-kaiops-core1-servicedown-knowledge.md
- ServiceDown
- e2e-20260721181052-mysql-kaiopsmysqlalertstablerowshigh-knowledge.md
- KaiOpsMySQLAlertsTableRowsHigh

Dependencies:
- prometheus
- alertmanager
- landing-pad
- rabbitmq
- context-agent
- resolution-agent
- approval-service
- remediation-engine

Validation checks:
- Prometheus rules API shows generated group
- Alertmanager delivered firing alerts
- Incident metadata shows context/resolution/remediation events

Rollback plan:
- Restore previous generated Prometheus rule file and reload Prometheus.

## Remediation Script
```bash
bash scripts/remediation/kaiops_alert_health_triage.sh --service landing-alert-e2e-20260721181052 --environment prod --api-gateway-url http://api-gateway:8000 --prometheus-url http://prometheus:9090 --mysql-host mysql --mysql-database kaiops --mysql-user kaiops --dry-run true
```
