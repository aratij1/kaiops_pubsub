kind: change
title: DW-1010 change context
services: customer-ingestion
deployment: incident-driven
change_id: CHG-DW-1010
source_system: internal
source_ref: DW-1010

# DW-1010 Schema Drift Detected change context

This change-context note supports troubleshooting for DW-1010 (schema_change).

## Summary
- Service: customer-ingestion
- Severity: CRITICAL
- Alert type: schema_change

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
