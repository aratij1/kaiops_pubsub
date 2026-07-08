kind: runbook
title: INC-9011 response runbook
services: orders-db
owner_team: platform-ops
last_reviewed: 2026-07-08
source_system: internal
source_ref: INC-9011

# INC-9011 INC-9011 orders database replica lag response runbook

Runbook checklist for responding to INC-9011.

## Triage
1. Confirm severity HIGH and affected service orders-db.
2. Collect logs, metrics, and dependency status.
3. Determine whether change/deployment regression is likely.

## Remediation
1. Apply safest reversible action first.
2. Validate recovery with objective metrics.
3. Record final root cause and preventive action.
