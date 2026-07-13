kind: change
title: test5 Rules Change Record
alert_id: test5-rule-change
alert_type: rules-change-plan
severity: warning
services: test5
deployment: prod
change_id: e0225edd-b61e-4386-84db-7967fe07b51e
source_system: monitoring-adapter
source_ref: workflow:5f25f38f-ad21-4847-bc95-abf7a80df19b
execution_plan: Deploy by environment with rollback guardrails and post-deploy SLO checks.
project_name: test5
selected_monitoring_tool: prometheus
workflow_id: 5f25f38f-ad21-4847-bc95-abf7a80df19b
onboarding_id: e0225edd-b61e-4386-84db-7967fe07b51e
trace_id: 24590c06-d6c0-4d86-9d2b-eb5b50460539
owner_team: sre

# test5 Rules Change Record

## Summary
Change record for generated monitoring rules and rollout governance.

## Description
This change introduces LLM-generated monitoring rules from plain-language requirements.
Rollout phases: staging validation, simulation review, governance approval, production deployment.

## Execution Plan
Deploy by environment with rollback guardrails and post-deploy SLO checks.
