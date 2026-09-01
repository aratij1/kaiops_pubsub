kind: runbook
title: etl-orders-dq-20260722141810 Alert Knowledge Onboarding
alert_type: configuration
severity: high
services: etl-orders-dq-20260722141810
recommended_action: Review generated draft and finalize onboarding knowledge.

# etl-orders-dq-20260722141810 Alert Knowledge Onboarding

## Summary
Auto-generated from 1 uploaded source document(s).

## Description
Auto-generated alert onboarding for etl-orders-dq-20260722141810.

Source evidence:
- [Service Knowledge] etl-orders-dq-20260722141810-prompt-service-knowledge.md: set up monitoring for mysql-exporter in prod. Owner is data-platform. Prometheus URL is http://prometheus:9090. Alert when exporter is down for 5 minutes or table rows grow unexpectedly. Dependencies are MySQL, Prometheu

Derived requirements:
- set up monitoring for mysql-exporter in prod. Owner is data-platform. Prometheus URL is http://prometheus:9090. Alert when exporter is down for 5 minutes or table rows grow unexpectedly. Dependencies are MySQL, Prometheus, and Grafana. Validate /metrics, Prometheus target up, DB connectivity, and row-count query. Rollback by restoring previous exporter config and restarting exporter.

Use this draft to refine final triage and remediation guidance.
