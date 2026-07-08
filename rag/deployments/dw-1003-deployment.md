kind: deployment
title: DW-1003 deployment context
services: oracle-source
deployment: incident-driven
source_system: internal
source_ref: DW-1003
last_reviewed: 2026-07-08

# DW-1003 Source System Unavailable deployment context

Deployment context used during triage for DW-1003.

## Checks
1. Identify latest deployment version and rollout window.
2. Compare incident start with release timing.
3. Validate rollback criteria and safety guardrails.
