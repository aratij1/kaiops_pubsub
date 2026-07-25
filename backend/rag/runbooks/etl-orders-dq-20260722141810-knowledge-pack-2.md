kind: runbook
title: etl-orders-dq-20260722141810 Knowledge Pack
services: etl-orders-dq-20260722141810
dependencies: mysql, Prometheus, Grafana
source_system: knowledge-pack
resolved_by: data-platform
environment: prod
knowledge_pack_status: approved
knowledge_pack_confidence: 0.65

# etl-orders-dq-20260722141810 Knowledge Pack

## Summary
Approved KaiOps knowledge pack for etl-orders-dq-20260722141810.

## Description
Knowledge pack for etl-orders-dq-20260722141810 in prod.

Alert patterns:
- Alert when CPU usage is above 80% for 5 minutes
- alert: Alert when CPU usage is above 80% for 5 minutes

Dependencies:
- mysql
- Prometheus
- Grafana

Validation checks:
- Validate /metrics, Prometheus target up, DB connectivity, and row-count query. Rollback by restoring previous exporter config and restarting exporter

Rollback plan:
- Rollback by restoring previous exporter config and restarting exporter

## Remediation Script
```bash
bash scripts/remediation/kaiops_alert_health_triage.sh --service etl-orders-dq-20260722141810 --environment prod --api-gateway-url http://api-gateway:8000 --prometheus-url http://prometheus:9090 --mysql-host mysql --mysql-database kaiops --mysql-user kaiops --dry-run true
```
