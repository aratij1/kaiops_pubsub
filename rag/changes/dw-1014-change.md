kind: change
title: DW-1014 change context
services: airflow
deployment: incident-driven
change_id: CHG-DW-1014
source_system: internal
source_ref: DW-1014

# DW-1014 Airflow Scheduler Down change context

This change-context note supports troubleshooting for DW-1014 (scheduler).

## Summary
- Service: airflow
- Severity: CRITICAL
- Alert type: scheduler

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
