kind: deployment
title: DW-1010 deployment context
services: customer-ingestion
deployment: incident-driven
source_system: internal
source_ref: DW-1010
last_reviewed: 2026-07-08

# DW-1010 Schema Drift Detected deployment context

Deployment context used during triage for DW-1010.

## Checks
1. Identify latest deployment version and rollout window.
2. Compare incident start with release timing.
3. Validate rollback criteria and safety guardrails.
