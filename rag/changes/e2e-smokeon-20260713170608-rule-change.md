kind: change
title: e2e-smokeon-20260713170608 Rules Change Record
alert_id: e2e-smokeon-20260713170608-rule-change
alert_type: rules-change-plan
severity: warning
services: e2e-smokeon-20260713170608
deployment: prod
change_id: afe52878-49af-4b26-b581-d0a9a15d77d6
source_system: monitoring-adapter
source_ref: workflow:b43edace-4c86-439f-b7f0-52b079e1bf7d
execution_plan: Deploy by environment with rollback guardrails and post-deploy SLO checks.
project_name: e2e-smokeon-20260713170608
selected_monitoring_tool: prometheus
workflow_id: b43edace-4c86-439f-b7f0-52b079e1bf7d
onboarding_id: afe52878-49af-4b26-b581-d0a9a15d77d6
trace_id: 6babace8-516f-4923-ba07-a09376493d8a
owner_team: platform-ops

# e2e-smokeon-20260713170608 Rules Change Record

## Summary
Change record for generated monitoring rules and rollout governance.

## Description
This change introduces LLM-generated monitoring rules from plain-language requirements.
Rollout phases: staging validation, simulation review, governance approval, production deployment.

## Execution Plan
Deploy by environment with rollback guardrails and post-deploy SLO checks.
