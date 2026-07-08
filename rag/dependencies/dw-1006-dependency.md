kind: dependency
title: DW-1006 dependency context
services: sales-fact-table
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1006
last_reviewed: 2026-07-08

# DW-1006 Missing Daily Partition dependency context

Dependency context for troubleshooting DW-1006.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
