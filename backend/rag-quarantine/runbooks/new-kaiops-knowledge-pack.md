kind: runbook
title: new_kaiops Knowledge Pack
services: new_kaiops
dependencies: mysql, Prometheus
source_system: knowledge-pack
resolved_by: data
environment: prod
knowledge_pack_status: approved
knowledge_pack_confidence: 0.755

# new_kaiops Knowledge Pack

## Summary
Approved KaiOps knowledge pack for new_kaiops.

## Description
Knowledge pack for new_kaiops in prod.

Alert patterns:
- KaiOpsMySQLAlertsTableRowsHigh

Dependencies:
- mysql
- Prometheus

Validation checks:
- Check recent growth with `SELECT DATE(created_at) AS day, COUNT(*) AS rows_added FROM alerts GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 7;`
- Check whether file watcher, Alertmanager replay, or test alerts are generating duplicate rows
- validate Alertmanager delivered the event to /alerts/alertmanager
- verify context retrieval touches this document for service mysql
- verify remediation action type is `script_execution`
- verify script output includes API gateway health, Prometheus alerts, and MySQL row count when credentials are available
- verify remediation emits execution logs and closure validation

Rollback plan:
- Rollback any threshold or routing change by restoring the previous Prometheus rule file and reloading Prometheus

## Remediation Script
```bash
bash scripts/remediation/kaiops_alert_health_triage.sh --service new_kaiops --environment prod --api-gateway-url http://api-gateway:8000 --prometheus-url http://prometheus:9090 --mysql-host mysql --mysql-database kaiops --mysql-user kaiops --dry-run true
```
