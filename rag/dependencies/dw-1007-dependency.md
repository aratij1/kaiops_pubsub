kind: dependency
title: DW-1007 dependency context
services: snowflake
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1007
last_reviewed: 2026-07-08

# DW-1007 Warehouse Storage Usage High dependency context

Dependency context for troubleshooting DW-1007.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
