kind: change
title: DW-1012 change context
services: customer-dimension
deployment: incident-driven
change_id: CHG-DW-1012
source_system: internal
source_ref: DW-1012

# DW-1012 Dimension Load Failure change context

This change-context note supports troubleshooting for DW-1012 (etl_failure).

## Summary
- Service: customer-dimension
- Severity: HIGH
- Alert type: etl_failure

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
