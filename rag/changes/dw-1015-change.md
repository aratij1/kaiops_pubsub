kind: change
title: DW-1015 change context
services: spark-cluster
deployment: incident-driven
change_id: CHG-DW-1015
source_system: internal
source_ref: DW-1015

# DW-1015 Spark Executor Memory Exhausted change context

This change-context note supports troubleshooting for DW-1015 (resource_utilization).

## Summary
- Service: spark-cluster
- Severity: HIGH
- Alert type: resource_utilization

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
