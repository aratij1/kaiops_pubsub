kind: change
title: DW-1002 change context
services: data-ingestion
deployment: incident-driven
change_id: CHG-DW-1002
source_system: internal
source_ref: DW-1002

# DW-1002 Data Load Delay change context

This change-context note supports troubleshooting for DW-1002 (sla_breach).

## Summary
- Service: data-ingestion
- Severity: HIGH
- Alert type: sla_breach

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
