# Prometheus + MySQL Monitoring to KaiOps Landing Pad

This guide configures Prometheus to monitor KaiOps services and MySQL, then routes firing alerts to KaiOps landing pad through Alertmanager -> Monitoring Adapter.

## What gets added

- Prometheus server at http://localhost:9090
- Alertmanager at http://localhost:9093
- MySQL exporter at http://localhost:9104/metrics
- Alertmanager webhook receiver: `POST /alerts/alertmanager` on monitoring-adapter

## End-to-end flow

1. Prometheus scrapes `/metrics` from KaiOps services and `mysql-exporter`.
2. Prometheus evaluates rules in `observability/alert.rules.yml`.
3. Firing alerts are sent to Alertmanager.
4. Alertmanager posts webhook payloads to `http://monitoring-adapter:8000/alerts/alertmanager`.
5. Monitoring adapter normalizes alerts and publishes to `raw-alerts`.
6. Alerts appear in UI landing pad (Dashboard -> Alert Stream) via existing pipeline.

## Files

- `docker-compose.yml`
- `observability/prometheus.yml`
- `observability/alert.rules.yml`
- `observability/alertmanager.yml`
- `services/monitoring-adapter/app.py`

## Start / restart

```powershell
docker compose up -d --build monitoring-adapter api-gateway prometheus alertmanager mysql-exporter ui
```

## Verify

```powershell
Invoke-RestMethod -Uri "http://localhost:9090/-/ready"
Invoke-RestMethod -Uri "http://localhost:9093/-/ready"
Invoke-RestMethod -Uri "http://localhost:9104/metrics"
```

Open:

- Prometheus targets: http://localhost:9090/targets
- Prometheus alerts: http://localhost:9090/alerts
- Alertmanager: http://localhost:9093
- KaiOps UI landing pad: http://localhost:8501

## Rule set included

- `KaiOpsServiceDown`
- `KaiOpsHighLatencyP95`
- `MySQLExporterDown`
- `MySQLTooManyConnections`

## Metadata for agent action

A runbook and onboarding readiness document are added to RAG corpus for this alert path:

- `rag/runbooks/prometheus-mysql-landing-pad-triage.md`
- `rag/onboarding/prometheus-mysql-monitoring-onboarding.md`

After edits, reload RAG index:

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8010/rag/reload" -ContentType "application/json" -Body "{}"
```
