# Troubleshooting Guide Sample - High Latency

Service: checkout-api
Environment: prod
Owner Team: sre-platform

## Trigger Condition
Latency alert when p95 response time > 500ms for 10m.

## Step-by-Step
1. Confirm alert in Prometheus and check current p95 trend.
2. Verify pod health and restart counts in the namespace.
3. Check database connection pool usage and lock wait time.
4. Inspect recent deployment and feature flag changes.
5. Validate queue backlog and retry storm indicators.

## Diagnostic Commands
- kubectl get pods -n prod | findstr checkout-api
- kubectl top pod -n prod | findstr checkout-api
- kubectl logs deployment/checkout-api -n prod --since=15m
- mysql -e "SHOW FULL PROCESSLIST;"

## Escalation
- Escalate to platform on-call if p95 remains > 500ms for 15m after mitigation.
- Escalate to database team if lock waits or replication lag exceed threshold.

## Evidence to Capture
- Alert screenshot and query link
- Pod metrics snapshot
- Deployment revision history
- DB processlist output
