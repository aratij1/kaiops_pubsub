# Payments API Monitoring Baseline

## Application Context
- Application: payments-api
- Owner Team: sre-platform
- Environment: prod
- Region: ap-south-1
- Namespace: payments

## Service Objectives
- p95 latency must stay below 500ms over 5m windows.
- HTTP 5xx rate must stay below 3 percent over 5m windows.
- Pod restart count should not exceed 3 in 10m for the deployment.

## Alert Rules (Plain English)
1. Trigger a critical alert when payments-api HTTP 5xx rate is greater than 3 percent for 5 minutes.
2. Trigger a high alert when p95 latency is greater than 500ms for 10 minutes.
3. Trigger a medium alert when kubernetes pod restarts for payments namespace are greater than 3 over 10 minutes.
4. Trigger a low alert when queue backlog is above 1000 for 15 minutes.

## Routing And Ownership
- Critical and high alerts route to sre-platform on-call.
- Medium and low alerts route to service owners first, then escalate after 15 minutes.
- Escalation contact: sre-platform@kaiops.local

## Runbook Hints
- For high latency, check database connection pool saturation and recent deploy activity.
- For 5xx spikes, inspect upstream dependency timeouts and API gateway logs.
- For restart spikes, check OOM kill events and node pressure.

## Metadata Mapping Hints
- Service: payments-api
- Business Unit: digital-payments
- Data Classification: internal
- Compliance Tags: pci, availability-tier-1

## Example Source Metrics
- http_server_requests_total{service="payments-api",status=~"5.."}
- http_server_request_duration_seconds_bucket{service="payments-api"}
- kube_pod_container_status_restarts_total{namespace="payments"}
- rabbitmq_queue_messages_ready{queue="payments-events"}

## Desired Generated Docs
- Monitoring SOP for payments-api
- Troubleshooting checklist for latency and 5xx
- Remediation playbook with rollback and safe restart steps
