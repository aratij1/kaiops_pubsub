kind: deployment
title: DW-1017 deployment context
services: daily-sales-report
deployment: incident-driven
source_system: internal
source_ref: DW-1017
last_reviewed: 2026-07-08

# DW-1017 Business SLA Missed deployment context

Deployment context used during triage for DW-1017.

## Checks
1. Identify latest deployment version and rollout window.
2. Compare incident start with release timing.
3. Validate rollback criteria and safety guardrails.
