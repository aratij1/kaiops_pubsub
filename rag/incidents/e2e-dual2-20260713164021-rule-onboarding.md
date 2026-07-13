kind: incident
title: e2e-dual2-20260713164021 Monitoring Rule Onboarding
alert_id: e2e-dual2-20260713164021-rule-onboarding
alert_type: monitoring-rule-onboarding
severity: high
services: e2e-dual2-20260713164021
deployment: prod
source_system: monitoring-adapter
source_ref: workflow:b6e39e89-f9c9-4c05-be93-3da31ebcb1bb
recommended_action: Review generated rules and approve production deployment.
project_name: e2e-dual2-20260713164021
selected_monitoring_tool: prometheus
workflow_id: b6e39e89-f9c9-4c05-be93-3da31ebcb1bb
onboarding_id: 786875d1-e609-4a27-9b84-5e1178557391
trace_id: 59a76042-651d-42cf-998b-648104ca0fd4
owner_team: platform-ops

# e2e-dual2-20260713164021 Monitoring Rule Onboarding

## Summary
Plain-language monitoring requirements were converted to prometheus rules.

## Description
Project e2e-dual2-20260713164021 onboarding completed in prod.
Selected tool: prometheus.
Requirements:
- Alert when CPU usage is above 82 for 5 minutes
- Alert when p95 latency is above 1600 for 10 minutes
- Alert when error rate is above 4 for 8 minutes

Generated rules:
- e2e-dual2-20260713164021-cpu-usage-percent-warning-prometheus (prometheus): avg(cpu_usage_percent[5m]) > 82.0
- e2e-dual2-20260713164021-request-latency-ms-p95-warning-prometheus (prometheus): p95(request_latency_ms_p95[10m]) > 1600.0
- e2e-dual2-20260713164021-error-rate-percent-warning-prometheus (prometheus): avg(error_rate_percent[8m]) > 4.0
