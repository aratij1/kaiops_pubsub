kind: deployment
title: ORDERS-REPLICA-LAG deployment context
services: orders-db
deployment: incident-driven
source_system: internal
source_ref: INC-NEW
last_reviewed: 2026-07-08

# Orders database replica lag deployment context

## Checks
1. Verify recent deployment version and rollout window.
2. Correlate deployment timeline with alert start.
3. Validate rollback criteria before executing changes.
