kind: runbook
title: DW-1014 response runbook
services: airflow
owner_team: platform-ops
last_reviewed: 2026-07-08
source_system: internal
source_ref: DW-1014

# DW-1014 Airflow Scheduler Down response runbook

Runbook checklist for responding to DW-1014.

## Triage
1. Confirm severity CRITICAL and affected service airflow.
2. Collect logs, metrics, and dependency status.
3. Determine whether change/deployment regression is likely.

## Remediation
1. Apply safest reversible action first.
2. Validate recovery with objective metrics.
3. Record final root cause and preventive action.
