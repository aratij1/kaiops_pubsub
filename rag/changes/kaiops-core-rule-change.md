kind: change
title: kaiops-core Rules Change Record
alert_id: kaiops-core-rule-change
alert_type: rules-change-plan
severity: warning
services: kaiops-core
deployment: prod
change_id: a115bd40-300c-4922-8c92-a50bf86c700b
source_system: monitoring-adapter
source_ref: workflow:0ffeee12-398d-4c3e-bd79-da74d9be542e
execution_plan: Deploy by environment with rollback guardrails and post-deploy SLO checks.
project_name: kaiops-core
selected_monitoring_tool: prometheus
workflow_id: 0ffeee12-398d-4c3e-bd79-da74d9be542e
onboarding_id: a115bd40-300c-4922-8c92-a50bf86c700b
trace_id: a706502d-8abf-4b7f-8ac1-e28ffc4184c3
owner_team: SRE

# kaiops-core Rules Change Record

## Summary
Change record for generated monitoring rules and rollout governance.

## Description
This change introduces LLM-generated monitoring rules from plain-language requirements.
Rollout phases: staging validation, simulation review, governance approval, production deployment.

## Execution Plan
Deploy by environment with rollback guardrails and post-deploy SLO checks.
