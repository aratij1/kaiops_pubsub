kind: runbook
title: Orders database replica lag response runbook
services: orders-db
owner_team: platform-ops
last_reviewed: 2026-07-08
source_system: internal
source_ref: INC-NEW

# Orders database replica lag response runbook

## Triage
1. Confirm alert severity CRITICAL and impacted service orders-db.
2. Check metrics, logs, and dependencies for anomaly start time.
3. Validate whether recent deployment/change windows overlap incident start.

## Remediation
1. Execute: Failover database.
2. Validate service recovery and alert stabilization.
3. Record root cause and prevention notes.
