kind: incident
title: test5 Monitoring Rule Onboarding
alert_id: test5-rule-onboarding
alert_type: monitoring-rule-onboarding
severity: high
services: test5
deployment: prod
source_system: monitoring-adapter
source_ref: workflow:5f25f38f-ad21-4847-bc95-abf7a80df19b
recommended_action: Review generated rules and approve production deployment.
project_name: test5
selected_monitoring_tool: prometheus
workflow_id: 5f25f38f-ad21-4847-bc95-abf7a80df19b
onboarding_id: e0225edd-b61e-4386-84db-7967fe07b51e
trace_id: 24590c06-d6c0-4d86-9d2b-eb5b50460539
owner_team: sre

# test5 Monitoring Rule Onboarding

## Summary
Plain-language monitoring requirements were converted to prometheus rules.

## Description
Project test5 onboarding completed in prod.
Selected tool: prometheus.
Requirements:
- alert when the services are down and then restart  it  if they are down in kaiops project

Generated rules:
- test5-cpu-usage-percent-warning-prometheus (prometheus): avg_over_time(cpu_usage_percent[5m]) > 80.0
