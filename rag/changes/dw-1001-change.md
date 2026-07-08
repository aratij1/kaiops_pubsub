kind: change
title: DW-1001 change context
services: airflow
deployment: incident-driven
change_id: CHG-DW-1001
source_system: internal
source_ref: DW-1001

# DW-1001 ETL Job Failure change context

This change-context note supports troubleshooting for DW-1001 (etl_failure).

## Summary
- Service: airflow
- Severity: CRITICAL
- Alert type: etl_failure

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
