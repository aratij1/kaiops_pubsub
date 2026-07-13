kind: incident
title: e2e-new-20260713163629 Monitoring Rule Onboarding
alert_id: e2e-new-20260713163629-rule-onboarding
alert_type: monitoring-rule-onboarding
severity: high
services: e2e-new-20260713163629
deployment: prod
source_system: monitoring-adapter
source_ref: workflow:e44cb933-b120-4c10-8a32-4ee81249e330
recommended_action: Review generated rules and approve production deployment.
project_name: e2e-new-20260713163629
selected_monitoring_tool: prometheus
workflow_id: e44cb933-b120-4c10-8a32-4ee81249e330
onboarding_id: b94b6b13-fc16-4099-81a4-7b9f3bb71c57
trace_id: 6bf1d099-b0e0-4443-bf51-0b375a8c20f6
owner_team: platform-ops

# e2e-new-20260713163629 Monitoring Rule Onboarding

## Summary
Plain-language monitoring requirements were converted to prometheus rules.

## Description
Project e2e-new-20260713163629 onboarding completed in prod.
Selected tool: prometheus.
Requirements:
- create a rule to test if records are more than 20 than raise alerts

Generated rules:
- e2e-new-20260713163629-cpu-usage-percent-warning-prometheus (prometheus): avg(cpu_usage_percent[5m]) > 80.0
