kind: change
title: DW-1006 change context
services: sales-fact-table
deployment: incident-driven
change_id: CHG-DW-1006
source_system: internal
source_ref: DW-1006

# DW-1006 Missing Daily Partition change context

This change-context note supports troubleshooting for DW-1006 (partition_missing).

## Summary
- Service: sales-fact-table
- Severity: HIGH
- Alert type: partition_missing

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
