kind: dependency
title: test5 Rule Dependency & RCA Metadata
alert_id: test5-rule-dependencies
alert_type: dependency-map
severity: warning
services: test5
deployment: prod
dependencies: prometheus, notification-platform, incident-orchestrator
source_system: monitoring-adapter
source_ref: workflow:5f25f38f-ad21-4847-bc95-abf7a80df19b
project_name: test5
selected_monitoring_tool: prometheus
workflow_id: 5f25f38f-ad21-4847-bc95-abf7a80df19b
onboarding_id: e0225edd-b61e-4386-84db-7967fe07b51e
trace_id: 24590c06-d6c0-4d86-9d2b-eb5b50460539
owner_team: sre

# test5 Rule Dependency & RCA Metadata

## Summary
Dependency and metadata baseline for rule monitoring, RCA, and resolution workflows.

## Description
Monitoring tool endpoint: not-provided.
Deployment mode: on_prem.
Track dependencies for data pipeline, scrape/export health, and notification delivery.
