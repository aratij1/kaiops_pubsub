kind: change
title: DW-1007 change context
services: snowflake
deployment: incident-driven
change_id: CHG-DW-1007
source_system: internal
source_ref: DW-1007

# DW-1007 Warehouse Storage Usage High change context

This change-context note supports troubleshooting for DW-1007 (capacity).

## Summary
- Service: snowflake
- Severity: HIGH
- Alert type: capacity

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
