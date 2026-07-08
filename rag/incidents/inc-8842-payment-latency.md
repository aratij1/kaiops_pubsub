alert_id: INC-8842
alert_name: INC-8842 payment latency after Deployment 2.5
service: payments
severity: high
alert_type: latency
source_system: internal
source_ref: INC-8842

# INC-8842 payment latency after Deployment 2.5

Deployment 2.5 increased checkout p95 latency for payments. Rollback restored
service health within minutes. The incident impacted payment authorization and
checkout completion latency.

Lessons learned:

- Tie alert onset to deployment windows.
- Use reversible remediation first for high-confidence deployment regressions.
- Keep payments-api rollback automation warm.
