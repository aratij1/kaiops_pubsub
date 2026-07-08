kind: change
title: DW-1013 change context
services: sales-fact
deployment: incident-driven
change_id: CHG-DW-1013
source_system: internal
source_ref: DW-1013

# DW-1013 Fact Table Record Count Mismatch change context

This change-context note supports troubleshooting for DW-1013 (reconciliation).

## Summary
- Service: sales-fact
- Severity: CRITICAL
- Alert type: reconciliation

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
