kind: dependency
title: DW-1013 dependency context
services: sales-fact
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1013
last_reviewed: 2026-07-08

# DW-1013 Fact Table Record Count Mismatch dependency context

Dependency context for troubleshooting DW-1013.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
