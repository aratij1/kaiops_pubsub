kind: runbook
title: Payments latency rollback
services: payments, checkout
deployment: Deployment 2.5

# Payments latency rollback

If payment checkout latency increases immediately after Deployment 2.5, compare
the alert start time with the deployment window. Prefer rollback of
`payments-api` before risky configuration changes.

Recommended remediation:

1. Confirm p95 latency and error-rate regression in Prometheus.
2. Notify payments-sre in the incident channel.
3. Roll back `payments-api` to the previous stable release.
4. Validate latency, CPU, and error-rate recovery.
