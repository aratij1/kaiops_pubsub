kind: change
title: ORDERS-REPLICA-LAG change context
services: orders-db
deployment: incident-driven
change_id: CHG-ORDERS-REPLICA-LAG
source_system: internal
source_ref: INC-NEW

# Orders database replica lag change context

## Summary
- Service: orders-db
- Severity: CRITICAL
- Alert: orders-replica-lag

## Operational Guidance
1. Check release and change windows around incident start.
2. Validate rollback possibility before irreversible remediation.
