kind: runbook
title: kaiops-core Rule Monitoring & Resolution Runbook
alert_id: kaiops-core-rule-runbook
alert_type: rule-operations
severity: high
services: kaiops-core
deployment: prod
source_system: monitoring-adapter
source_ref: workflow:0ffeee12-398d-4c3e-bd79-da74d9be542e
root_cause: Threshold drift, metric quality, or dependency changes can cause noisy or delayed alerts.
impact: Delayed detection and unnecessary incidents for production services.
execution_plan: Tune rule thresholds, re-run simulation, then promote approved rules.
recommended_action: Use workflow simulation and governance checks before production push.
project_name: kaiops-core
selected_monitoring_tool: prometheus
workflow_id: 0ffeee12-398d-4c3e-bd79-da74d9be542e
onboarding_id: a115bd40-300c-4922-8c92-a50bf86c700b
trace_id: a706502d-8abf-4b7f-8ac1-e28ffc4184c3
owner_team: SRE

# kaiops-core Rule Monitoring & Resolution Runbook

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
