kind: dependency
title: kaiops-core Rule Dependency & RCA Metadata
alert_id: kaiops-core-rule-dependencies
alert_type: dependency-map
severity: warning
services: kaiops-core
deployment: prod
dependencies: prometheus, notification-platform, incident-orchestrator
source_system: monitoring-adapter
source_ref: workflow:0ffeee12-398d-4c3e-bd79-da74d9be542e
project_name: kaiops-core
selected_monitoring_tool: prometheus
workflow_id: 0ffeee12-398d-4c3e-bd79-da74d9be542e
onboarding_id: a115bd40-300c-4922-8c92-a50bf86c700b
trace_id: a706502d-8abf-4b7f-8ac1-e28ffc4184c3
owner_team: SRE

# kaiops-core Rule Dependency & RCA Metadata

## Summary
Dependency and metadata baseline for rule monitoring, RCA, and resolution workflows.

## Description
Monitoring tool endpoint: http://prometheus:9090.
Deployment mode: on_prem.
Track dependencies for data pipeline, scrape/export health, and notification delivery.
