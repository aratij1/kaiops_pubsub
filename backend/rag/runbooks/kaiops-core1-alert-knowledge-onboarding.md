kind: runbook
title: kaiops-core1 Alert Knowledge Onboarding
alert_type: configuration
severity: high
services: kaiops-core1
recommended_action: Review generated draft and finalize onboarding knowledge.

# kaiops-core1 Alert Knowledge Onboarding

## Summary
Auto-generated from 1 uploaded source document(s).

## Description
Auto-generated alert onboarding for kaiops-core1.

Source evidence:
- [Service Knowledge] kaiops-core1-prompt-service-knowledge.md: Set up production monitoring for mysql-exporter. The service owner is data-platform, and Prometheus is available at http://prometheus:9090. Create a critical alert when the exporter remains unavailable for 5 minutes and

Derived requirements:
- Set up production monitoring for mysql-exporter. The service owner is data-platform, and Prometheus is available at http://prometheus:9090. Create a critical alert when the exporter remains unavailable for 5 minutes and a warning alert when table-row growth exceeds the configured threshold. Validate Prometheus metrics, MySQL connectivity, exporter health and the row-count query. Dependencies include MySQL, Prometheus and Grafana. If validation fails, restore the previous exporter configuration and restart the exporter

Use this draft to refine final triage and remediation guidance.
