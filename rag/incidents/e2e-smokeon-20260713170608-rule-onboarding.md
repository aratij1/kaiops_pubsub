kind: incident
title: e2e-smokeon-20260713170608 Monitoring Rule Onboarding
alert_id: e2e-smokeon-20260713170608-rule-onboarding
alert_type: monitoring-rule-onboarding
severity: high
services: e2e-smokeon-20260713170608
deployment: prod
source_system: monitoring-adapter
source_ref: workflow:b43edace-4c86-439f-b7f0-52b079e1bf7d
recommended_action: Review generated rules and approve production deployment.
project_name: e2e-smokeon-20260713170608
selected_monitoring_tool: prometheus
workflow_id: b43edace-4c86-439f-b7f0-52b079e1bf7d
onboarding_id: afe52878-49af-4b26-b581-d0a9a15d77d6
trace_id: 6babace8-516f-4923-ba07-a09376493d8a
owner_team: platform-ops

# e2e-smokeon-20260713170608 Monitoring Rule Onboarding

## Summary
Plain-language monitoring requirements were converted to prometheus rules.

## Description
Project e2e-smokeon-20260713170608 onboarding completed in prod.
Selected tool: prometheus.
Requirements:
- Alert when CPU usage is above 80 for 5 minutes

Generated rules:
- e2e-smokeon-20260713170608-cpu-usage-percent-warning-prometheus (prometheus): avg_over_time(cpu_usage_percent[5m]) > 80.0
