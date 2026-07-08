# KaiMS Demo Guide for End Users and Executives

This guide provides one demo flow with two presentation tracks:
- Executive track: business outcomes and governance.
- End-user track: hands-on operations in the UI.

## Demo Link

Open this demo guide directly:
- docs/DEMO_EXECUTIVE_AND_END_USER.md

Open the product UI locally:
- http://localhost:8501

## Audience Tracks

## 1) Executive Track (10-12 minutes)

Objective:
- Show risk reduction, faster incident response, and governance controls.

Narrative:
1. Incident enters from monitoring and is safety-checked.
2. AI agents perform RCA, context enrichment, and remediation recommendation.
3. Human approval is enforced for high and critical risk.
4. Remediation and closure are validated and recorded.
5. FinOps and audit trail provide cost and compliance transparency.

Business outcomes to call out:
- Faster MTTD/MTTR.
- Fewer manual handoffs.
- Controlled automation with human gates.
- Full observability and auditability.

Executive screens to show:
1. Incident Summary tab.
2. Agent Flow tab (status by role).
3. Gateway Safety tab.
4. FinOps tab.
5. Closed Incidents tab.

## 2) End User Track (15-20 minutes)

Objective:
- Show daily operational workflow for SRE and support teams.

Hands-on path:
1. In sidebar, click Load Latest Alerts.
2. In Alerts and Quick Docs tab:
   - filter by severity,
   - open View Runbook / View Incident / View RCA.
3. Start a flow from alert stream.
4. In Agent Flow tab:
   - inspect each role,
   - open drill-down details.
5. If approval is required (HIGH or CRITICAL):
   - approve, reject, or modify.
6. In Gateway Safety tab:
   - show request decision and recent events.
7. In FinOps tab:
   - review token and cost usage.
8. In Closed Incidents tab:
   - verify closure report and lessons learned.

## Suggested Demo Scenario

Use this sample for consistent storytelling:
- database-replica-lag

Why:
- High business impact,
- clear remediation path,
- approval flow and closure are easy to demonstrate.

## Presenter Script (Short)

Use this exact script if needed.

Opening:
- "KaiMS receives alerts, applies safety checks, runs multi-agent RCA, and guides or automates remediation with governance."

During flow:
- "This is the same incident lifecycle from raw alert to closure, with traceability at every step."

At approval:
- "Only high and critical incidents require explicit human approval before continuation."

At FinOps:
- "Every model call is tracked for token and cost transparency."

At closure:
- "Closure is validated and captured for future reuse, reducing repeat incident effort."

## Success Criteria Checklist

- Alert appears in alert stream.
- Flow executes and Agent Flow updates.
- Guidance links return runbook/incident/RCA matches.
- Approval step appears only when severity is HIGH or CRITICAL.
- Closure report is visible in Closed Incidents.
- FinOps entries are visible for model usage.

## Fallback Plan (If Something Fails)

1. Refresh alerts and gateway events.
2. Run a sample flow from API gateway:
   - POST /sample/{flow_id}/workflow
3. Use local in-process workflow mode if Kafka path is unavailable.

## Reference Links

- README.md
- docs/WINDOWS_UPDATE_AND_RUN.md
- docs/DEMO_EXECUTIVE_AND_END_USER.md

