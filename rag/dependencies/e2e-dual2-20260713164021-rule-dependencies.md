kind: dependency
title: e2e-dual2-20260713164021 Rule Dependency & RCA Metadata
alert_id: e2e-dual2-20260713164021-rule-dependencies
alert_type: dependency-map
severity: warning
services: e2e-dual2-20260713164021
deployment: prod
dependencies: prometheus, notification-platform, incident-orchestrator
source_system: monitoring-adapter
source_ref: workflow:b6e39e89-f9c9-4c05-be93-3da31ebcb1bb
project_name: e2e-dual2-20260713164021
selected_monitoring_tool: prometheus
workflow_id: b6e39e89-f9c9-4c05-be93-3da31ebcb1bb
onboarding_id: 786875d1-e609-4a27-9b84-5e1178557391
trace_id: 59a76042-651d-42cf-998b-648104ca0fd4
owner_team: platform-ops

# e2e-dual2-20260713164021 Rule Dependency & RCA Metadata

## Summary
Dependency and metadata baseline for rule monitoring, RCA, and resolution workflows.

## Description
Monitoring tool endpoint: http://prometheus:9090.
Deployment mode: on_prem.
Track dependencies for data pipeline, scrape/export health, and notification delivery.
