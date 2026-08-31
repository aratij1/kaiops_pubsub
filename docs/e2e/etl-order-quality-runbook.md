# Order ETL Data Quality Runbook

Service: etl-orders-dq
Environment: prod
Owner: data-platform

## Alert Patterns
- Alert when null customer ID ratio is above 20 percent for 5 minutes.
- Alert when rejected ETL rows are greater than zero in the latest landing batch.
- Alert when ETL load latency is above 120 seconds.

## Dependencies
- MySQL landing table `etl_order_quality_events`
- Prometheus scrape and alert routing
- KaiOps context agent RAG index

## Triage
1. Check the latest landed batch row counts.
2. Validate rejected rows by `dq_status` and `dq_reason`.
3. Compare source file row count with loaded table row count.
4. Inspect upstream order feed for missing `customer_id` or negative `amount`.

## Remediation
Command: powershell -ExecutionPolicy Bypass -File scripts/reprocess-etl-orders.ps1 -Project etl-orders-dq
Rollback: mark the failed batch as quarantined and replay the previous clean file.
Validation: query MySQL for rejected rows and confirm null customer ID ratio is below 20 percent.
