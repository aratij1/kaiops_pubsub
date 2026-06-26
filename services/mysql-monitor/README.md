# MySQL Monitor App

A lightweight FastAPI monitoring service for MySQL.

## Features

- Health endpoint with MySQL ping status.
- Periodic server sampling (status and server metadata).
- Processlist inspection endpoint.
- Replication status endpoint (supports both REPLICA and SLAVE commands).
- Prometheus metrics endpoint.
- Automatic alert ingestion into KaiOps via API Gateway `/alerts`.

## Endpoints

- `GET /` : service summary
- `GET /healthz` : MySQL health status
- `GET /mysql/status` : latest sampled MySQL status
- `GET /mysql/processlist?limit=20` : top active processes
- `GET /mysql/replication` : replication details
- `GET /metrics` : Prometheus metrics

## Environment Variables

- `MYSQL_HOST` (default: `localhost`)
- `MYSQL_PORT` (default: `3306`)
- `MYSQL_USER` (default: `root`)
- `MYSQL_PASSWORD` (default: empty)
- `MYSQL_DATABASE` (default: empty)
- `MYSQL_POLL_SECONDS` (default: `15`, minimum `5`)
- `MYSQL_CONNECT_TIMEOUT` (default: `5`)
- `MYSQL_ALERTS_ENABLED` (default: `true`)
- `MYSQL_ALERT_COOLDOWN_SECONDS` (default: `300`)
- `MYSQL_THREADS_RUNNING_THRESHOLD` (default: `40`)
- `MYSQL_SLOW_QUERIES_DELTA_THRESHOLD` (default: `5`)
- `MYSQL_ABORTED_CONNECTS_DELTA_THRESHOLD` (default: `3`)
- `KAIOPS_ALERT_ENDPOINT` (default: `http://localhost:8010/alerts`)
- `KAIOPS_ALERT_TIMEOUT_SECONDS` (default: `8`)

## Run Locally (PowerShell)

```powershell
$env:MYSQL_HOST = "localhost"
$env:MYSQL_PORT = "3306"
$env:MYSQL_USER = "root"
$env:MYSQL_PASSWORD = "your-password"
$env:MYSQL_DATABASE = "kaips"
$env:KAIOPS_ALERT_ENDPOINT = "http://localhost:8010/alerts"

.\.venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8011 --app-dir services/mysql-monitor
```

Then open:

- http://localhost:8011/healthz
- http://localhost:8011/mysql/status
- http://localhost:8011/metrics

## Alert Ingestion Behavior

When enabled, mysql-monitor sends alerts into KaiOps for these conditions:

- `MySQLUnavailable` (critical)
- `MySQLThreadsRunningHigh` (high)
- `MySQLSlowQueriesSpike` (warning)
- `MySQLAbortedConnectsSpike` (critical)

To avoid alert storms, each alert type is rate-limited with cooldown.
