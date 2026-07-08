kind: deployment
title: INC-9011 deployment context
services: orders-db
deployment: incident-driven
source_system: internal
source_ref: INC-9011
last_reviewed: 2026-07-08

# INC-9011 INC-9011 orders database replica lag deployment context

Deployment context used during triage for INC-9011.

## Checks
1. Identify latest deployment version and rollout window.
2. Compare incident start with release timing.
3. Validate rollback criteria and safety guardrails.
