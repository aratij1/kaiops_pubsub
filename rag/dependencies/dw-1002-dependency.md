kind: dependency
title: DW-1002 dependency context
services: data-ingestion
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1002
last_reviewed: 2026-07-08

# DW-1002 Data Load Delay dependency context

Dependency context for troubleshooting DW-1002.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
