kind: change
title: INC-9011 change context
services: orders-db
deployment: incident-driven
change_id: CHG-INC-9011
source_system: internal
source_ref: INC-9011

# INC-9011 INC-9011 orders database replica lag change context

This change-context note supports troubleshooting for INC-9011 (replication).

## Summary
- Service: orders-db
- Severity: HIGH
- Alert type: replication

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
