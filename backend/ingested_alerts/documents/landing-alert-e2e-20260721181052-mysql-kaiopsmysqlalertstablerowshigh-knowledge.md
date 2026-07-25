# KaiOpsMySQLAlertsTableRowsHigh Knowledge And Remediation Guide
Kind: runbook
Alert: KaiOpsMySQLAlertsTableRowsHigh
Service: mysql
Environment: prod
Severity: warning
Source alert file: 20260721T081108745158Z_kaiopsmysqlalertstablerowshigh_46e408884901f001.json
Fingerprint: 46e408884901f001

## Signal
Prometheus alert `KaiOpsMySQLAlertsTableRowsHigh` fires when
`kaiops_mysql_alerts_table_rows{database="kaiops",table="alerts"}` is above the configured threshold.
The affected connector is `kaiops-mysql`; the affected database is `kaiops`; the affected table is `alerts`.

## Investigation
- Confirm the alert labels match service=mysql and environment=prod.
- Inspect the latest landing-pad payload and compare the alert fingerprint with 46e408884901f001.
- Review Prometheus graph and Alertmanager delivery status for this alert.
- Query row count with `SELECT COUNT(*) AS alert_rows FROM alerts;`.
- Check recent growth with `SELECT DATE(created_at) AS day, COUNT(*) AS rows_added FROM alerts GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 7;`.
- Check whether file watcher, Alertmanager replay, or test alerts are generating duplicate rows.

## Remediation
- Run the guarded dry-run script first and review evidence.
- If cleanup is required, use the `kaiops-mysql` connector archive operation only after approval.
- Do not run ad hoc delete commands from the UI.

## Remediation Script
```bash
sh scripts/remediation/kaiops_alert_health_triage.sh --service mysql --environment prod --api-gateway-url http://api-gateway:8000 --prometheus-url http://prometheus:9090 --mysql-host mysql --mysql-database kaiops --mysql-user kaiops --alerts-table alerts --dry-run true
```

## Rollback
Rollback any threshold or routing change by restoring the previous Prometheus rule file and reloading Prometheus.

## Validation Checks
- validate Alertmanager delivered the event to /alerts/alertmanager.
- verify context retrieval touches this document for service mysql.
- verify remediation action type is `script_execution`.
- verify script output includes API gateway health, Prometheus alerts, and MySQL row count when credentials are available.
- verify remediation emits execution logs and closure validation.
