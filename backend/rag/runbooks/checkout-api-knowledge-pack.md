kind: runbook
title: checkout-api Knowledge Pack
services: checkout-api
dependencies: checkout
source_system: knowledge-pack
resolved_by: platform-ops
environment: prod
knowledge_pack_status: approved
knowledge_pack_confidence: 0.552

# checkout-api Knowledge Pack

## Summary
Approved KaiOps knowledge pack for checkout-api.

## Description
Knowledge pack for checkout-api in prod.

Alert patterns:

Dependencies:
- checkout

Validation checks:
- checkout-runbook.md
- checkout-api

Rollback plan:

## Remediation Script
```bash
bash scripts/remediation/kaiops_alert_health_triage.sh --service checkout-api --environment prod --api-gateway-url http://api-gateway:8000 --prometheus-url http://prometheus:9090 --mysql-host mysql --mysql-database kaiops --mysql-user kaiops --dry-run true
```
