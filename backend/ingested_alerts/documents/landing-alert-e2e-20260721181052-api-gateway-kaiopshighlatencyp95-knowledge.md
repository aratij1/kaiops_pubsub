# KaiOpsHighLatencyP95 Knowledge And Remediation Guide
Kind: runbook
Alert: KaiOpsHighLatencyP95
Service: api-gateway
Environment: prod
Severity: warning
Source alert file: 20260721T085448985645Z_kaiopshighlatencyp95_217f818bfd942ddf.json
Fingerprint: 217f818bfd942ddf

## Signal
Service api-gateway operation /route p95 latency is above 2s.

## Investigation
- Confirm the alert labels match service=api-gateway and environment=prod.
- Inspect the latest landing-pad payload and compare the alert fingerprint with 217f818bfd942ddf.
- Review Prometheus graph and Alertmanager delivery status for this alert.
- Check recent deployments, dependency health, queue lag, database saturation, and API latency for the service.

## Remediation
- If this is latency or service-down, scale or restart the affected service only after approval.
- If this is MySQL/data-quality related, run a read-only count query first, archive old rows if approved, and verify downstream consumers recover.
- If this is an onboarding smoke alert, validate routing, topic delivery, worker processing, context retrieval, resolution, approval, remediation, and closure.

## Remediation Script
```bash
bash scripts/remediation/kaiops_alert_health_triage.sh --service api-gateway --environment prod --api-gateway-url http://api-gateway:8000 --prometheus-url http://prometheus:9090 --mysql-host mysql --mysql-database kaiops --mysql-user kaiops --dry-run true
```

## Rollback
Rollback any threshold or routing change by restoring the previous Prometheus rule file and reloading Prometheus.

## Validation Checks
- validate Alertmanager delivered the event to /alerts/alertmanager.
- verify context retrieval touches this document for service api-gateway.
- verify remediation emits execution logs and closure validation.
