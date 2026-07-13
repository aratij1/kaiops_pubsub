kind: runbook
title: test5 Rule Monitoring & Resolution Runbook
alert_id: test5-rule-runbook
alert_type: rule-operations
severity: high
services: test5
deployment: prod
source_system: monitoring-adapter
source_ref: workflow:5f25f38f-ad21-4847-bc95-abf7a80df19b
root_cause: Threshold drift, metric quality, or dependency changes can cause noisy or delayed alerts.
impact: Delayed detection and unnecessary incidents for production services.
execution_plan: Tune rule thresholds, re-run simulation, then promote approved rules.
recommended_action: Use workflow simulation and governance checks before production push.
project_name: test5
selected_monitoring_tool: prometheus
workflow_id: 5f25f38f-ad21-4847-bc95-abf7a80df19b
onboarding_id: e0225edd-b61e-4386-84db-7967fe07b51e
trace_id: 24590c06-d6c0-4d86-9d2b-eb5b50460539
owner_team: sre

# test5 Rule Monitoring & Resolution Runbook

## Summary
Operational runbook for monitoring generated rules, triage, RCA, and resolution.

## Description
1. Verify rule expression output for false positives.
2. Validate alert routing and escalation channels.
3. Run RCA checklist for noisy or missed alerts.
4. Apply threshold or duration tuning and redeploy through workflow editor.
5. Confirm health restoration and close incident with audit notes.

## Root Cause
Threshold drift, metric quality, or dependency changes can cause noisy or delayed alerts.

## Impact
Delayed detection and unnecessary incidents for production services.

## Execution Plan
Tune rule thresholds, re-run simulation, then promote approved rules.
