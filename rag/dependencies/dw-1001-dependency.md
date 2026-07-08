kind: dependency
title: DW-1001 dependency context
services: airflow
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1001
last_reviewed: 2026-07-08

# DW-1001 ETL Job Failure dependency context

Dependency context for troubleshooting DW-1001.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
