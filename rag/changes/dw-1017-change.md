kind: change
title: DW-1017 change context
services: daily-sales-report
deployment: incident-driven
change_id: CHG-DW-1017
source_system: internal
source_ref: DW-1017

# DW-1017 Business SLA Missed change context

This change-context note supports troubleshooting for DW-1017 (sla_breach).

## Summary
- Service: daily-sales-report
- Severity: CRITICAL
- Alert type: sla_breach

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
