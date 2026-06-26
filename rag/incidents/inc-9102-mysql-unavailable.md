# INC-9102: MySQL Unavailable From Monitoring Agent

## Issue

The MySQL monitor raises `MySQLUnavailable` alerts when it cannot authenticate or connect to the configured MySQL endpoint.

Common error patterns:
- Access denied for user
- Connection refused
- Host unreachable
- Timeout reached during connect

## Troubleshooting

1. Validate connectivity
- Confirm host and port are reachable from the monitor host.
- Verify firewall rules for MySQL port 3306.

2. Validate credentials
- Confirm `DB_USER` and `DB_PASSWORD` values.
- Verify account permissions include basic read metadata access.

3. Validate monitor configuration
- Check `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`.
- Confirm `KAIOPS_ALERT_ENDPOINT` points to API Gateway `/alerts`.

4. Validate service runtime
- Check mysql-monitor health endpoint `/healthz`.
- Review `last_error` and `last_alert_error` values.

## Resolution

- Correct MySQL credentials and restart mysql-monitor.
- Ensure network access from monitor runtime to MySQL.
- Set appropriate alert thresholds and cooldown to avoid repeated noise during transient outages.
- After recovery, verify alerts clear and new alerts are no longer emitted.

## Post-Resolution Validation

- `/healthz` returns `mysql_up=true`.
- `/alerts/all` shows no continuous new `MySQLUnavailable` entries.
- Alert stream displays new alerts with actionable context only.
