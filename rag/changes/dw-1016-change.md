kind: change
title: DW-1016 change context
services: cdc-pipeline
deployment: incident-driven
change_id: CHG-DW-1016
source_system: internal
source_ref: DW-1016

# DW-1016 Failed CDC Processing change context

This change-context note supports troubleshooting for DW-1016 (change_data_capture).

## Summary
- Service: cdc-pipeline
- Severity: CRITICAL
- Alert type: change_data_capture

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
