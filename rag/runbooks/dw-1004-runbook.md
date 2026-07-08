kind: runbook
title: DW-1004 response runbook
services: kafka-ingestion
owner_team: platform-ops
last_reviewed: 2026-07-08
source_system: internal
source_ref: DW-1004

# DW-1004 Kafka Consumer Lag High response runbook

Runbook checklist for responding to DW-1004.

## Triage
1. Confirm severity HIGH and affected service kafka-ingestion.
2. Collect logs, metrics, and dependency status.
3. Determine whether change/deployment regression is likely.

## Remediation
1. Apply safest reversible action first.
2. Validate recovery with objective metrics.
3. Record final root cause and preventive action.
