kind: deployment
title: DW-1002 deployment context
services: data-ingestion
deployment: incident-driven
source_system: internal
source_ref: DW-1002
last_reviewed: 2026-07-08

# DW-1002 Data Load Delay deployment context

Deployment context used during triage for DW-1002.

## Checks
1. Identify latest deployment version and rollout window.
2. Compare incident start with release timing.
3. Validate rollback criteria and safety guardrails.
