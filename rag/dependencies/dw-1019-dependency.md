kind: dependency
title: DW-1019 dependency context
services: data-warehouse
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1019
last_reviewed: 2026-07-08

# DW-1019 Unauthorized Data Access Attempt dependency context

Dependency context for troubleshooting DW-1019.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
