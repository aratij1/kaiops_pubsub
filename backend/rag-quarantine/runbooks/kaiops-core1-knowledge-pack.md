kind: runbook
title: kaiops-core1 Knowledge Pack
services: kaiops-core1
dependencies: mysql, Prometheus, Grafana
source_system: knowledge-pack
resolved_by: kaiops-platform
environment: prod
knowledge_pack_status: approved
knowledge_pack_confidence: 0.65

# kaiops-core1 Knowledge Pack

## Summary
Approved KaiOps knowledge pack for kaiops-core1.

## Description
Knowledge pack for kaiops-core1 in prod.

Alert patterns:
- test

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
bash scripts/remediation/kaiops_alert_health_triage.sh --service kaiops-core1 --environment prod --api-gateway-url http://api-gateway:8000 --prometheus-url http://prometheus:9090 --mysql-host mysql --mysql-database kaiops --mysql-user kaiops --dry-run true
```
