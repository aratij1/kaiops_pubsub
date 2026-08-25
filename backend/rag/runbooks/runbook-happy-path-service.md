kind: runbook
title: Runbook - happy-path-service
alert_type: happy-path-service-monitoring
severity: critical
services: happy-path-service
tenant_id: default
environment: prod
namespace: default
source: rule-generation-agent
application_id: dba6f71b-97e1-4e55-b8c3-bd5f86a9c4f3
context_strategy: similar-historical-tickets-first
historical_ticket_count: 3
historical_ticket_paths: /app/rag/incidents/dw-1007-warehouse-storage-usage-high.md,/app/rag/incidents/dw-1004-kafka-consumer-lag-high.md,/app/rag/incidents/dw-1015-spark-executor-memory-exhausted.md

# Runbook - happy-path-service

## Summary
Auto-generated monitoring runbook for happy-path-service (prod).

## Description
Auto-generated monitoring runbook for **happy-path-service**.

- Tenant: default
- Environment: prod
- Namespace: default
- Owner team: sre-team

## Historical Ticket Context
The following similar resolved incidents were discovered before this runbook was generated:
### dw 1007 warehouse storage usage high
- Similarity: 0.268
- Evidence: # Warehouse Storage Usage High (DW-1007) Service: snowflake Severity: HIGH Alert type: capacity ## Summary Warehouse storage usage is approaching or above capacity thresholds. ## Symptoms - Storage alerts firing - Slower maintenance operations ## Root Cause - Data growth - Stale historical data ## Impact - Service: snowflake Severity: MEDIUM Alert type: capacity ## Dependencies - Not explicitly documented. ## Deployment Context - Not explicitly documented. ## Execution Plan - Archive old partitions job ## Investigation Timeline 1. Review storage trends 2. Find stale tables and partitions 3. Check retention policy ## Remediation - Purge unused tables - Archive old partitions - Increase storag
- Source ticket: `/app/rag/incidents/dw-1007-warehouse-storage-usage-high.md`

### dw 1004 kafka consumer lag high
- Similarity: 0.260
- Evidence: # Kafka Consumer Lag High (DW-1004) Service: kafka-ingestion Severity: HIGH Alert type: streaming ## Summary Streaming consumer lag is increasing and records are not being processed in time. ## Symptoms - Consumer lag rising - Records accumulating in queue - Throughput decreasing ## Root Cause - Slow consumers - High message volume - Consumer crash ## Impact - Service: kafka-ingestion Severity: HIGH Alert type: streaming ## Dependencies - Not explicitly documented. ## Deployment Context - Not explicitly documented. ## Execution Plan - kubectl scale deployment kafka-consumer --replicas=5 ## Investigation Timeline 1. Inspect consumer lag metrics 2. Check consumer logs 3. Review partition balan
- Source ticket: `/app/rag/incidents/dw-1004-kafka-consumer-lag-high.md`

### dw 1015 spark executor memory exhausted
- Similarity: 0.260
- Evidence: # Spark Executor Memory Exhausted (DW-1015) Service: spark-cluster Severity: HIGH Alert type: resource_utilization ## Summary Spark executor resources were exhausted during job execution. ## Symptoms - Executor OOM - Job retries - Task failures due to memory pressure ## Root Cause - Data skew - Large shuffle operations ## Impact - Service: spark-cluster Severity: HIGH Alert type: resource_utilization ## Dependencies - Not explicitly documented. ## Deployment Context - Not explicitly documented. ## Execution Plan - Increase executor memory ## Investigation Timeline 1. Check executor memory and spill metrics 2. Inspect shuffle size 3. Review partition distribution ## Remediation - Increase exe
- Source ticket: `/app/rag/incidents/dw-1015-spark-executor-memory-exhausted.md`

## Alert Rules
### happy-path-service-target-down (critical)
- Condition: `(up{job="happy-path-service"} == 0) or absent(up{job="happy-path-service"})` for `2m`
- Summary: happy-path-service target is down
- Description: Prometheus cannot scrape the application target.
- Troubleshooting steps:
  - Confirm the service process is running and healthy.
  - Check recent deploys/restarts for this service.
  - Verify network connectivity between Prometheus and the target.

### happy-path-service-cpu-high (warning)
- Condition: `rate(process_cpu_seconds_total{job="happy-path-service"}[5m]) > 0.85` for `5m`
- Summary: happy-path-service CPU usage high
- Description: Sustained CPU saturation detected.
- Troubleshooting steps:
  - Inspect recent traffic spikes or inefficient code paths.
  - Check for runaway background jobs or retry storms.
  - Consider scaling out if load is legitimate.

### happy-path-service-memory-high (warning)
- Condition: `process_resident_memory_bytes{job="happy-path-service"} > 5e+08` for `10m`
- Summary: happy-path-service memory usage high
- Description: Sustained memory growth detected.
- Troubleshooting steps:
  - Check for memory leaks via recent deploys.
  - Inspect cache sizes and unbounded in-memory collections.
  - Consider a rolling restart if growth is unbounded.
