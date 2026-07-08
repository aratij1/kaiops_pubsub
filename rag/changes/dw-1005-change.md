kind: change
title: DW-1005 change context
services: dq-framework
deployment: incident-driven
change_id: CHG-DW-1005
source_system: internal
source_ref: DW-1005

# DW-1005 Data Quality Check Failed change context

This change-context note supports troubleshooting for DW-1005 (data_quality).

## Summary
- Service: dq-framework
- Severity: CRITICAL
- Alert type: data_quality

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
