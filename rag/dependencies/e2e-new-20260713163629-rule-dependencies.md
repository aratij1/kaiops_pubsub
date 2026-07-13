kind: dependency
title: e2e-new-20260713163629 Rule Dependency & RCA Metadata
alert_id: e2e-new-20260713163629-rule-dependencies
alert_type: dependency-map
severity: warning
services: e2e-new-20260713163629
deployment: prod
dependencies: prometheus, notification-platform, incident-orchestrator
source_system: monitoring-adapter
source_ref: workflow:e44cb933-b120-4c10-8a32-4ee81249e330
project_name: e2e-new-20260713163629
selected_monitoring_tool: prometheus
workflow_id: e44cb933-b120-4c10-8a32-4ee81249e330
onboarding_id: b94b6b13-fc16-4099-81a4-7b9f3bb71c57
trace_id: 6bf1d099-b0e0-4443-bf51-0b375a8c20f6
owner_team: platform-ops

# e2e-new-20260713163629 Rule Dependency & RCA Metadata

## Summary
Dependency and metadata baseline for rule monitoring, RCA, and resolution workflows.

## Description
Monitoring tool endpoint: http://prometheus:9090.
Deployment mode: on_prem.
Track dependencies for data pipeline, scrape/export health, and notification delivery.
