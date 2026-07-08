kind: change
title: DW-1004 change context
services: kafka-ingestion
deployment: incident-driven
change_id: CHG-DW-1004
source_system: internal
source_ref: DW-1004

# DW-1004 Kafka Consumer Lag High change context

This change-context note supports troubleshooting for DW-1004 (streaming).

## Summary
- Service: kafka-ingestion
- Severity: HIGH
- Alert type: streaming

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
