kind: incident
title: kaiops-core Monitoring Rule Onboarding
alert_id: kaiops-core-rule-onboarding
alert_type: monitoring-rule-onboarding
severity: high
services: kaiops-core
deployment: prod
source_system: monitoring-adapter
source_ref: workflow:0ffeee12-398d-4c3e-bd79-da74d9be542e
recommended_action: Review generated rules and approve production deployment.
project_name: kaiops-core
selected_monitoring_tool: prometheus
workflow_id: 0ffeee12-398d-4c3e-bd79-da74d9be542e
onboarding_id: a115bd40-300c-4922-8c92-a50bf86c700b
trace_id: a706502d-8abf-4b7f-8ac1-e28ffc4184c3
owner_team: SRE

# kaiops-core Monitoring Rule Onboarding

## Summary
Plain-language monitoring requirements were converted to prometheus rules.

## Description
Project kaiops-core onboarding completed in prod.
Selected tool: prometheus.
Requirements:
- create rule if any table has 0 records

Generated rules:
- kaiops-core-cpu-usage-percent-warning-prometheus (prometheus): avg_over_time(cpu_usage_percent[5m]) > 80.0
