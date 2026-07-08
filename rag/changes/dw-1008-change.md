kind: change
title: DW-1008 change context
services: data-warehouse
deployment: incident-driven
change_id: CHG-DW-1008
source_system: internal
source_ref: DW-1008

# DW-1008 Query Performance Degradation change context

This change-context note supports troubleshooting for DW-1008 (performance).

## Summary
- Service: data-warehouse
- Severity: HIGH
- Alert type: performance

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
