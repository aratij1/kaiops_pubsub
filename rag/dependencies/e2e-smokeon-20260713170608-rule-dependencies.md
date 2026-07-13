kind: dependency
title: e2e-smokeon-20260713170608 Rule Dependency & RCA Metadata
alert_id: e2e-smokeon-20260713170608-rule-dependencies
alert_type: dependency-map
severity: warning
services: e2e-smokeon-20260713170608
deployment: prod
dependencies: prometheus, notification-platform, incident-orchestrator
source_system: monitoring-adapter
source_ref: workflow:b43edace-4c86-439f-b7f0-52b079e1bf7d
project_name: e2e-smokeon-20260713170608
selected_monitoring_tool: prometheus
workflow_id: b43edace-4c86-439f-b7f0-52b079e1bf7d
onboarding_id: afe52878-49af-4b26-b581-d0a9a15d77d6
trace_id: 6babace8-516f-4923-ba07-a09376493d8a
owner_team: platform-ops

# e2e-smokeon-20260713170608 Rule Dependency & RCA Metadata

## Summary
Dependency and metadata baseline for rule monitoring, RCA, and resolution workflows.

## Description
Monitoring tool endpoint: http://prometheus:9090.
Deployment mode: on_prem.
Track dependencies for data pipeline, scrape/export health, and notification delivery.
