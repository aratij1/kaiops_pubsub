kind: runbook
title: landing-alert-e2e-20260721181052 Knowledge Pack
services: landing-alert-e2e-20260721181052
dependencies: mysql, Prometheus, Grafana
source_system: knowledge-pack
resolved_by: platform-ops
environment: prod
knowledge_pack_status: approved
knowledge_pack_confidence: 0.755

# landing-alert-e2e-20260721181052 Knowledge Pack

## Summary
Approved KaiOps knowledge pack for landing-alert-e2e-20260721181052.

## Description
Knowledge pack for landing-alert-e2e-20260721181052 in prod.

Alert patterns:
- e2e-20260721181052-prompt-service-knowledge.md

Dependencies:
- mysql
- Prometheus
- Grafana

Validation checks:
- Validate Prometheus metrics, MySQL connectivity, exporter health and the row-count query. Dependencies include MySQL, Prometheus and Grafana. If validation fails, restore the previous expo

Rollback plan:
- restore the previous exporter configuration and restart the exporter

## Remediation Script
```bash
bash scripts/remediation/kaiops_alert_health_triage.sh --service landing-alert-e2e-20260721181052 --environment prod --api-gateway-url http://api-gateway:8000 --prometheus-url http://prometheus:9090 --mysql-host mysql --mysql-database kaiops --mysql-user kaiops --dry-run true
```
