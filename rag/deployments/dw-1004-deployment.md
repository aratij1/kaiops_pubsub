kind: deployment
title: DW-1004 deployment context
services: kafka-ingestion
deployment: incident-driven
source_system: internal
source_ref: DW-1004
last_reviewed: 2026-07-08

# DW-1004 Kafka Consumer Lag High deployment context

Deployment context used during triage for DW-1004.

## Checks
1. Identify latest deployment version and rollout window.
2. Compare incident start with release timing.
3. Validate rollback criteria and safety guardrails.
