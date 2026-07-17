# Alert Flow Catalog

_Auto-generated from RAG incident documents whenever flows.json is rebuilt. Edit the source incident docs and resubmit them — this file is overwritten on every rebuild and excluded from RAG document matching._

## Airflow Scheduler Down
- **Service:** airflow
- **Severity:** CRITICAL
- **Alert Type:** scheduler
- **Alert ID:** DW-1014
- **Summary:** Service: airflow
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** systemctl restart airflow-scheduler

## Auth session store hotspot
- **Service:** auth-session
- **Severity:** CRITICAL
- **Alert Type:** datastore_hotspot
- **Alert ID:** AUTH-SESSION-STORE-HOTSPOT
- **Summary:** Authentication sessions concentrated on a hot shard and increased login latency.
- **Recommended Action:** Investigate issue
- **Root Cause:** Uneven shard key distribution in session persistence layer
- **Impact:** Intermittent login slowdowns and token refresh failures
- **Execution Plan:** 1. Identify hot shard

## Business SLA Missed
- **Service:** daily-sales-report
- **Severity:** CRITICAL
- **Alert Type:** sla_breach
- **Alert ID:** DW-1017
- **Summary:** Service: daily-sales-report
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Trigger delayed pipeline job; Scale workers if backlog continues

## Catalog cache stale reads
- **Service:** catalog-api
- **Severity:** CRITICAL
- **Alert Type:** cache
- **Alert ID:** CATALOG-CACHE-STALE
- **Summary:** Catalog API served stale cache entries after invalidation lag.
- **Recommended Action:** Investigate issue
- **Root Cause:** Redis invalidation consumer lag
- **Impact:** Customers saw outdated product availability
- **Execution Plan:** 1. Check Redis consumer lag

## Dashboard Refresh Failure
- **Service:** powerbi-reporting
- **Severity:** HIGH
- **Alert Type:** reporting
- **Alert ID:** DW-1020
- **Summary:** Service: powerbi-reporting
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Restart refresh job

## Data Load Delay
- **Service:** data-ingestion
- **Severity:** HIGH
- **Alert Type:** sla_breach
- **Alert ID:** DW-1002
- **Summary:** Service: data-ingestion
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Trigger delayed pipeline job; Scale workers if backlog continues

## Data Pipeline Backlog Growing
- **Service:** data-pipeline
- **Severity:** HIGH
- **Alert Type:** backlog
- **Alert ID:** DW-1018
- **Summary:** Service: data-pipeline
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Scale processing cluster

## Data Quality Check Failed
- **Service:** dq-framework
- **Severity:** CRITICAL
- **Alert Type:** data_quality
- **Alert ID:** DW-1005
- **Summary:** Service: dq-framework
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Run dq validation job

## Dimension Load Failure
- **Service:** customer-dimension
- **Severity:** HIGH
- **Alert Type:** etl_failure
- **Alert ID:** DW-1012
- **Summary:** Service: customer-dimension
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** airflow dags trigger sales_etl

## ETL Job Failure
- **Service:** airflow
- **Severity:** CRITICAL
- **Alert Type:** etl_failure
- **Alert ID:** DW-1001
- **Summary:** Service: airflow
- **Recommended Action:** Investigate issue
- **Deployment:** ETL workflow / DAG changes for sales_etl
- **Execution Plan:** airflow dags trigger sales_etl; validate DAG logs; re-run workflow if safe

## Fact Table Record Count Mismatch
- **Service:** sales-fact
- **Severity:** CRITICAL
- **Alert Type:** reconciliation
- **Alert ID:** DW-1013
- **Summary:** Service: sales-fact
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Reload affected partition

## Failed CDC Processing
- **Service:** cdc-pipeline
- **Severity:** CRITICAL
- **Alert Type:** change_data_capture
- **Alert ID:** DW-1016
- **Summary:** Service: cdc-pipeline
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Restart CDC connector

## HighNetworkLatency Incident Summary
- **Service:** blackbox
- **Severity:** HIGH
- **Alert Type:** HighNetworkLatency
- **Alert ID:** 5baeecf4-994e-45b8-b3ec-96006786a23e
- **Summary:** HighNetworkLatency detected for blackbox. Impact: Blackbox service impact requires immediate triage.
- **Recommended Action:** Rollback deployment
- **Root Cause:** Deployment 2.5
- **Impact:** Blackbox service impact requires immediate triage

## HighNetworkPacketLoss Incident Summary
- **Service:** blackbox
- **Severity:** CRITICAL
- **Alert Type:** HighNetworkPacketLoss
- **Alert ID:** 0669dbc6-d12e-4ec5-b6ed-2bc1eaa06d4f
- **Summary:** HighNetworkPacketLoss detected for blackbox. Impact: Blackbox service impact requires immediate triage.
- **Recommended Action:** Rollback deployment
- **Root Cause:** Deployment 2.5
- **Impact:** Blackbox service impact requires immediate triage

## INC-8842 payment latency after Deployment 2.5
- **Service:** payments
- **Severity:** HIGH
- **Alert Type:** latency
- **Alert ID:** INC-8842
- **Summary:** Service: payments
- **Recommended Action:** Investigate issue
- **Deployment:** Deployment 2.5
- **Execution Plan:** Confirm checkout latency regression; Roll back deployment; Validate SLO recovery

## INC-9011 orders database replica lag
- **Service:** orders-db
- **Severity:** HIGH
- **Alert Type:** replication
- **Alert ID:** INC-9011
- **Summary:** Service: orders-db
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Not explicitly documented.

## Kafka Consumer Lag High
- **Service:** kafka-ingestion
- **Severity:** HIGH
- **Alert Type:** streaming
- **Alert ID:** DW-1004
- **Summary:** Service: kafka-ingestion
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** kubectl scale deployment kafka-consumer --replicas=5

## KaiOps Service Health Baseline
- **Service:** api-gateway
- **Severity:** HIGH
- **Alert Type:** availability
- **Alert ID:** KAIOPS-SERVICE-HEALTH-BASELINE
- **Summary:** Real Prometheus-based service health monitoring for KaiOps microservices
- **Recommended Action:** Investigate issue

## KaiOpsServiceDown Incident Summary
- **Service:** kaiops-orchestrator
- **Severity:** CRITICAL
- **Alert Type:** KaiOpsServiceDown
- **Alert ID:** b2f5ab95-99d2-4202-9f9b-17b453081676
- **Summary:** KaiOpsServiceDown detected for kaiops-orchestrator. Impact: Kaiops-Orchestrator service impact requires immediate triage.
- **Recommended Action:** Rollback deployment
- **Root Cause:** Deployment 2.5
- **Impact:** Kaiops-Orchestrator service impact requires immediate triage

## KaiOpsServiceDown Incident Summary
- **Service:** kaiops-core1
- **Severity:** CRITICAL
- **Alert Type:** KaiOpsServiceDown
- **Alert ID:** c455c797-af5d-4abd-8c13-b44b53b5f0db
- **Summary:** KaiOpsServiceDown detected for kaiops-core1. Impact: Kaiops-Core1 service impact requires immediate triage.
- **Recommended Action:** Rollback deployment
- **Root Cause:** Deployment 2.5
- **Impact:** Kaiops-Core1 service impact requires immediate triage

## Late Arriving Data
- **Service:** transaction-feed
- **Severity:** HIGH
- **Alert Type:** data_latency
- **Alert ID:** DW-1011
- **Summary:** Service: transaction-feed
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Execute incremental load

## Missing Daily Partition
- **Service:** sales-fact-table
- **Severity:** HIGH
- **Alert Type:** partition_missing
- **Alert ID:** DW-1006
- **Summary:** Service: sales-fact-table
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Backfill partition script

## MySQL Exporter Availability Baseline
- **Service:** mysql
- **Severity:** CRITICAL
- **Alert Type:** database
- **Alert ID:** MYSQL-EXPORTER-AVAILABILITY-BASELINE
- **Summary:** Real Prometheus-based MySQL exporter and DB signal monitoring
- **Recommended Action:** Investigate issue

## Orders database replica lag
- **Service:** orders-db
- **Severity:** CRITICAL
- **Alert Type:** incident
- **Alert ID:** ORDERS-REPLICA-LAG
- **Summary:** Service: orders-db
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Failover database

## Payments webhook retry storm
- **Service:** payments-webhook
- **Severity:** CRITICAL
- **Alert Type:** retry_storm
- **Alert ID:** PAYMENTS-WEBHOOK-RETRY-STORM
- **Summary:** Payments webhooks retried aggressively after downstream 429 responses.
- **Recommended Action:** Investigate issue
- **Root Cause:** Missing exponential backoff on webhook dispatcher
- **Impact:** Delayed merchant notifications and elevated queue depth
- **Execution Plan:** 1. Inspect retry queue depth

## Query Performance Degradation
- **Service:** data-warehouse
- **Severity:** HIGH
- **Alert Type:** performance
- **Alert ID:** DW-1008
- **Summary:** Service: data-warehouse
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Refresh warehouse stats

## RAG_doc
- **Service:** unknown
- **Severity:** HIGH
- **Alert Type:** incident
- **Alert ID:** RAG-DOC
- **Summary:** PK     ! ß¤ÒlZ      [Content_Types].xml ¢(                                                                                                                                                                     
- **Recommended Action:** Investigate issue

## Replication Lag Exceeded Threshold
- **Service:** replication-service
- **Severity:** HIGH
- **Alert Type:** replication
- **Alert ID:** DW-1009
- **Summary:** Service: replication-service
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Restart replication service

## Schema Drift Detected
- **Service:** customer-ingestion
- **Severity:** CRITICAL
- **Alert Type:** schema_change
- **Alert ID:** DW-1010
- **Summary:** Service: customer-ingestion
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Regenerate ingestion schemas

## ServiceDown Incident Summary
- **Service:** kaiops-model-router
- **Severity:** CRITICAL
- **Alert Type:** ServiceDown
- **Alert ID:** 593b8ce5-2336-4d09-8f84-5324fcc0b333
- **Summary:** ServiceDown detected for kaiops-model-router.
- **Recommended Action:** Investigate issue

## ServiceDown Incident Summary
- **Service:** kaiops-resolution-agent
- **Severity:** CRITICAL
- **Alert Type:** ServiceDown
- **Alert ID:** db91cf05-db73-4b4b-b1b9-0fe5d280c8a8
- **Summary:** ServiceDown detected for kaiops-resolution-agent. Impact: Kaiops-Resolution-Agent service impact requires immediate triage.
- **Recommended Action:** Rollback deployment
- **Root Cause:** Deployment 2.5
- **Impact:** Kaiops-Resolution-Agent service impact requires immediate triage

## Source System Unavailable
- **Service:** oracle-source
- **Severity:** CRITICAL
- **Alert Type:** source_connectivity
- **Alert ID:** DW-1003
- **Summary:** Service: oracle-source
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Run source connectivity probe

## Spark Executor Memory Exhausted
- **Service:** spark-cluster
- **Severity:** HIGH
- **Alert Type:** resource_utilization
- **Alert ID:** DW-1015
- **Summary:** Service: spark-cluster
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Increase executor memory

## Unauthorized Data Access Attempt
- **Service:** data-warehouse
- **Severity:** CRITICAL
- **Alert Type:** security
- **Alert ID:** DW-1019
- **Summary:** Service: data-warehouse
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Disable affected user immediately

## Warehouse Storage Usage High
- **Service:** snowflake
- **Severity:** HIGH
- **Alert Type:** capacity
- **Alert ID:** DW-1007
- **Summary:** Service: snowflake
- **Recommended Action:** Investigate issue
- **Deployment:** Not explicitly documented.
- **Execution Plan:** Archive old partitions job
