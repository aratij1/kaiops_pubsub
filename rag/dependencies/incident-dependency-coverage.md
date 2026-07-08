kind: dependency
title: Incident dependency coverage matrix
services: airflow, cdc-pipeline, customer-dimension, customer-ingestion, daily-sales-report, data-ingestion, data-pipeline, data-warehouse, dq-framework, kafka-ingestion, oracle-source, orders-db, payments, powerbi-reporting, replication-service, sales-fact, sales-fact-table, snowflake, spark-cluster, transaction-feed, unknown
dependencies: service-catalog, cmdb, observability
source_system: internal
source_ref: RAG-COVERAGE-DEPENDENCIES
last_reviewed: 2026-07-08

# Incident Dependency Coverage Matrix

This document maintains dependency-context coverage for all incident/alert entries in rag/incidents.

## Coverage
- DW-1001 | airflow | Dependencies should be validated before remediation execution.
- DW-1002 | data-ingestion | Dependencies should be validated before remediation execution.
- DW-1003 | oracle-source | Dependencies should be validated before remediation execution.
- DW-1004 | kafka-ingestion | Dependencies should be validated before remediation execution.
- DW-1005 | dq-framework | Dependencies should be validated before remediation execution.
- DW-1006 | sales-fact-table | Dependencies should be validated before remediation execution.
- DW-1007 | snowflake | Dependencies should be validated before remediation execution.
- DW-1008 | data-warehouse | Dependencies should be validated before remediation execution.
- DW-1009 | replication-service | Dependencies should be validated before remediation execution.
- DW-1010 | customer-ingestion | Dependencies should be validated before remediation execution.
- DW-1011 | transaction-feed | Dependencies should be validated before remediation execution.
- DW-1012 | customer-dimension | Dependencies should be validated before remediation execution.
- DW-1013 | sales-fact | Dependencies should be validated before remediation execution.
- DW-1014 | airflow | Dependencies should be validated before remediation execution.
- DW-1015 | spark-cluster | Dependencies should be validated before remediation execution.
- DW-1016 | cdc-pipeline | Dependencies should be validated before remediation execution.
- DW-1017 | daily-sales-report | Dependencies should be validated before remediation execution.
- DW-1018 | data-pipeline | Dependencies should be validated before remediation execution.
- DW-1019 | data-warehouse | Dependencies should be validated before remediation execution.
- DW-1020 | powerbi-reporting | Dependencies should be validated before remediation execution.
- INC-8842 | payments | Dependencies should be validated before remediation execution.
- INC-9011 | orders-db | Dependencies should be validated before remediation execution.
- RAG-DOC | unknown | Dependencies should be validated before remediation execution.
