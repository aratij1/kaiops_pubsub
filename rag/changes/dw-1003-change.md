kind: change
title: DW-1003 change context
services: oracle-source
deployment: incident-driven
change_id: CHG-DW-1003
source_system: internal
source_ref: DW-1003

# DW-1003 Source System Unavailable change context

This change-context note supports troubleshooting for DW-1003 (source_connectivity).

## Summary
- Service: oracle-source
- Severity: CRITICAL
- Alert type: source_connectivity

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
