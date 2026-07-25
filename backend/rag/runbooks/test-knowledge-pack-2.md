kind: runbook
title: test Knowledge Pack
services: test
dependencies: MySQL, Prometheus
source_system: knowledge-pack
resolved_by: sr
environment: prod
knowledge_pack_status: approved
knowledge_pack_confidence: 0.755

# test Knowledge Pack

## Summary
Approved KaiOps knowledge pack for test.

## Description
Knowledge pack for test in prod.

Alert patterns:
- # MySQL-Exporter-Availability-Baseline (2).md
- # MySQL Exporter Availability Baseline

Dependencies:
- MySQL
- Prometheus

Validation checks:
- validate exporter container, credential config, target scrape status, and DB connection limits to restore telemetry and service safety

Rollback plan:
- restore telemetry and service safety

## Queries
- validate exporter container, credential config, target scrape status, and DB connection limits to restore telemetry and service safety
