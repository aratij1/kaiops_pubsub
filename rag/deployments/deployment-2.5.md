kind: deployment
title: Deployment 2.5 payments-api release
services: payments
deployment: Deployment 2.5

# Deployment 2.5 payments-api release

Deployment 2.5 changed payment timeout handling and checkout retry behavior.
The deployment touched `payments-api`, downstream `checkout`, and ledger
authorization paths.

## Incident Decision Link (INC-8842)
- Description: p95 latency above 1200ms for payments checkout path after Deployment 2.5.
- Recommended Action: Roll back deployment.
- Root Cause: Deployment 2.5.
- Impact: Payment latency.
- Risk Tier: HIGH.
- Execution Mode: HUMAN-APPROVAL.
- Approval Required: YES.
- Policy Reason: Severity in mandatory approval set; rollback requires approver confirmation.

Risk indicators:

- Increased p95 latency
- Increased checkout retry rate
- Higher payment authorization queue depth
