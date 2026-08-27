kind: runbook
title: etl-orders-dq-20260721130504 Knowledge Pack
services: etl-orders-dq-20260721130504
dependencies: MySQL, Prometheus
source_system: knowledge-pack
resolved_by: data-platform
environment: prod
knowledge_pack_status: approved
knowledge_pack_confidence: 0.855

# etl-orders-dq-20260721130504 Knowledge Pack

## Summary
Approved KaiOps knowledge pack for etl-orders-dq-20260721130504.

## Description
Knowledge pack for etl-orders-dq-20260721130504 in prod.

Alert patterns:
- Alert when ETL load latency is above 120 seconds

Dependencies:
- MySQL
- Prometheus

Validation checks:
- Check the latest landed batch row counts
- Validate rejected rows by `dq_status` and `dq_reason`

Rollback plan:
- Rollback: mark the failed batch as quarantined and replay the previous clean file

## Remediation Script
```bash
bash scripts/remediation/kaiops_alert_health_triage.sh --service etl-orders-dq-20260721130504 --environment prod --api-gateway-url http://api-gateway:8000 --prometheus-url http://prometheus:9090 --mysql-host mysql --mysql-database kaiops --mysql-user kaiops --dry-run true
```
