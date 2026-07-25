kind: runbook
title: kaiops-platform Knowledge Pack
services: kaiops-platform
dependencies: prometheus, mysql, redis, kafka, rabbitmq
source_system: knowledge-pack
resolved_by: platform-ops
environment: prod
knowledge_pack_status: approved
knowledge_pack_confidence: 0.755

# kaiops-platform Knowledge Pack

## Summary
Approved KaiOps knowledge pack for kaiops-platform.

## Description
Knowledge pack for kaiops-platform in prod.

Alert patterns:
- Alert name: KaiOpsHighLatencyP95

Dependencies:
- prometheus
- mysql
- redis
- kafka
- rabbitmq

Validation checks:
- Validate alert labels include service, severity, and alert_status=firing

Rollback plan:
- rollback recent risky deployment if needed

## Remediation Script
```bash
bash scripts/remediation/kaiops_alert_health_triage.sh --service kaiops-platform --environment prod --api-gateway-url http://api-gateway:8000 --prometheus-url http://prometheus:9090 --mysql-host mysql --mysql-database kaiops --mysql-user kaiops --dry-run true
```
