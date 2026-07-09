alert_id: <INC-XXXX or DW-XXXX>
alert_name: <alert name>
service: <service>
severity: <critical|high|warning|info>
alert_type: <incident type>
source_system: <servicenow|jira|pagerduty|other>
source_ref: <ticket id or URL>
dependencies: <comma-separated dependency list>
deployment: <deployment, release, or build reference>
execution_plan: <summary of commands or automated steps>
resolved_by: <team or user>
closed_at: <YYYY-MM-DD>

# <Incident Title>

## Summary
Describe what happened in 3-5 lines.

## Symptoms
- Symptom 1
- Symptom 2

## Root Cause
Describe verified root cause.

## Impact
Describe customer/business/technical impact.

## Dependencies
List upstream/downstream systems, teams, or services that materially affect this incident.

## Deployment Context
Capture the deployment, release, or configuration change that may have triggered or influenced the issue.

## Execution Plan
Describe the approved action path, including commands, automation steps, and rollback criteria.

## Investigation Timeline
1. Time - action
2. Time - finding
3. Time - decision

## Remediation
- Corrective action taken
- Validation evidence

## Prevention
- Follow-up action 1
- Follow-up action 2

## SOP Notes
Link to related runbook/SOP if available.

## Consolidated Intake Guidance
Collect the incident in this order:
1. Basic identity: alert, service, severity, source, and ticket reference.
2. Environment context: dependencies, deployment/release, and affected system state.
3. Execution data: commands, automation, rollback steps, and validation checks.
4. Operational findings: symptoms, root cause, impact, and remediation evidence.
