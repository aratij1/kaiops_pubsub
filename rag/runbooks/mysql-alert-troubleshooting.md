# Runbook: MySQL Monitor Alert Troubleshooting

## Issue

This runbook covers these alert types:
- `MySQLUnavailable`
- `MySQLThreadsRunningHigh`
- `MySQLSlowQueriesSpike`
- `MySQLAbortedConnectsSpike`

## Troubleshooting

### A. MySQLUnavailable
1. Check DB connectivity and credentials.
2. Confirm environment variables are present in launcher/runtime.
3. Confirm MySQL user has required access.

### B. MySQLThreadsRunningHigh
1. Inspect active sessions using process list.
2. Identify long-running queries and lock waits.
3. Check application connection pooling behavior.

### C. MySQLSlowQueriesSpike
1. Enable and inspect slow query log.
2. Check query plans and missing indexes.
3. Correlate with deployment/change windows.

### D. MySQLAbortedConnectsSpike
1. Check authentication failures and client retries.
2. Inspect max connections and pool saturation.
3. Validate TLS/auth plugin compatibility.

## Resolution

- Tune thresholds and cooldown in mysql-monitor alert config.
- Fix DB credentials and rotate secrets if needed.
- Optimize high-latency queries and add indexes.
- Reduce connection churn using stable client pooling.
- Re-run health checks and verify alert trend normalizes.

## Quick Commands

- Check monitor health: `GET /healthz`
- Check monitor config: `GET /alerts/config`
- Update config: `POST /alerts/config`
- Check raised alerts: `GET /alerts/all`
- Search RAG guidance: `GET /rag/search?query=mysql+troubleshooting+resolution`
