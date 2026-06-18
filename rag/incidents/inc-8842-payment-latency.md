kind: incident
title: INC-8842 payment latency after Deployment 2.5
services: payments, checkout
deployment: Deployment 2.5

# INC-8842 payment latency after Deployment 2.5

Deployment 2.5 increased checkout p95 latency for payments. Rollback restored
service health within minutes. The incident impacted payment authorization and
checkout completion latency.

Lessons learned:

- Tie alert onset to deployment windows.
- Use reversible remediation first for high-confidence deployment regressions.
- Keep payments-api rollback automation warm.
