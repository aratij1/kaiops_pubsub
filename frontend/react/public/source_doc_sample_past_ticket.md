# Past Ticket Sample - Payments API 5xx Burst

Ticket ID: INC-2026-0701-1142
Service: payments-api
Environment: prod
Severity: high
Opened At: 2026-07-01T11:42:00Z

## Symptom
Customer checkout failed with intermittent HTTP 502/504 errors.

## Scope
- Region: ap-south-1
- Affected Pods: payments-api-7d9f8b6c7f-2z8mn, payments-api-7d9f8b6c7f-l4f2k
- Error Rate: 4.8% over 10 minutes

## Investigation Notes
1. Verified alert fired for 5xx ratio > 3% over 5m.
2. Observed upstream timeout spikes from gateway to payments-api.
3. Checked recent deployment and found config update 15 minutes before incident.

## Resolution
- Rolled back deployment to previous stable revision.
- Restarted affected pods.
- Error rate returned below 1% in 7 minutes.

## Follow-up Requirements
- Add rollback guidance to runbook.
- Add alert for upstream timeout saturation.
- Attach post-incident RCA for future onboarding context.
