kind: deployment
title: DW-1006 deployment context
services: sales-fact-table
deployment: incident-driven
source_system: internal
source_ref: DW-1006
last_reviewed: 2026-07-08

# DW-1006 Missing Daily Partition deployment context

Deployment context used during triage for DW-1006.

## Checks
1. Identify latest deployment version and rollout window.
2. Compare incident start with release timing.
3. Validate rollback criteria and safety guardrails.
