kind: change
title: DW-1009 change context
services: replication-service
deployment: incident-driven
change_id: CHG-DW-1009
source_system: internal
source_ref: DW-1009

# DW-1009 Replication Lag Exceeded Threshold change context

This change-context note supports troubleshooting for DW-1009 (replication).

## Summary
- Service: replication-service
- Severity: HIGH
- Alert type: replication

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
