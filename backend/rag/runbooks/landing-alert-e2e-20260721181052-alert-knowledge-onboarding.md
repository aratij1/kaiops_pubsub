kind: runbook
title: landing-alert-e2e-20260721181052 Alert Knowledge Onboarding
alert_type: availability
severity: high
services: landing-alert-e2e-20260721181052
recommended_action: Review generated draft and finalize onboarding knowledge.

# landing-alert-e2e-20260721181052 Alert Knowledge Onboarding

## Summary
Auto-generated from 1 uploaded source document(s).

## Description
Auto-generated alert onboarding for landing-alert-e2e-20260721181052.

Source evidence:
- [Service Knowledge] landing-alert-e2e-20260721181052-prompt-service-knowledge.md: Set up production monitoring for mysql-exporter. The service owner is data-platform, and Prometheus is available at http://prometheus:9090. Create a critical alert when the exporter remains unavailable for 5 minutes and

Derived requirements:
- landing-alert-e2e-20260721181052-prompt-service-knowledge.md: Set up production monitoring for mysql-exporter. The service owner is data-platform, and Prometheus is available at http://prometheus:9090. Create a critical alert when the exporter remains unavailable for 5 minutes and a warning alert when table-row growth exceeds the configured threshold. Validate Prometheus metrics, MySQL connectivity, exporter health and the row-count query. Dependencies include MySQL, Prometheus and Grafana. If validation fails, restore the previous exporter configuration and restart the exporter

Use this draft to refine final triage and remediation guidance.
