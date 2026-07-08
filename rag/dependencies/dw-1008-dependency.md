kind: dependency
title: DW-1008 dependency context
services: data-warehouse
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1008
last_reviewed: 2026-07-08

# DW-1008 Query Performance Degradation dependency context

Dependency context for troubleshooting DW-1008.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
