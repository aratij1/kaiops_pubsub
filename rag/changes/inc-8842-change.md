kind: change
title: INC-8842 change context
services: payments
deployment: incident-driven
change_id: CHG-INC-8842
source_system: internal
source_ref: INC-8842

# INC-8842 INC-8842 payment latency after Deployment 2.5 change context

This change-context note supports troubleshooting for INC-8842 (latency).

## Summary
- Service: payments
- Severity: HIGH
- Alert type: latency

## Decision Snapshot
- Description: p95 latency above 1200ms for payments checkout path after Deployment 2.5.
- Recommended Action: Roll back deployment.
- Root Cause: Deployment 2.5.
- Impact: Payment latency.
- Risk Tier: HIGH.
- Execution Mode: HUMAN-APPROVAL.
- Approval Required: YES.
- Policy Reason: Severity in mandatory approval set; rollback requires approver confirmation.

## Operational Guidance
1. Validate recent deployments and config changes affecting this service.
2. Correlate alert start time with release/change windows.
3. Prefer reversible remediation if change regression is suspected.
