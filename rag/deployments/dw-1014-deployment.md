kind: deployment
title: DW-1014 deployment context
services: airflow
deployment: incident-driven
source_system: internal
source_ref: DW-1014
last_reviewed: 2026-07-08

# DW-1014 Airflow Scheduler Down deployment context

Deployment context used during triage for DW-1014.

## Checks
1. Identify latest deployment version and rollout window.
2. Compare incident start with release timing.
3. Validate rollback criteria and safety guardrails.
