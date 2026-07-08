kind: dependency
title: DW-1004 dependency context
services: kafka-ingestion
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1004
last_reviewed: 2026-07-08

# DW-1004 Kafka Consumer Lag High dependency context

Dependency context for troubleshooting DW-1004.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
