kind: dependency
title: DW-1011 dependency context
services: transaction-feed
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1011
last_reviewed: 2026-07-08

# DW-1011 Late Arriving Data dependency context

Dependency context for troubleshooting DW-1011.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
