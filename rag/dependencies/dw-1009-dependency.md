kind: dependency
title: DW-1009 dependency context
services: replication-service
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1009
last_reviewed: 2026-07-08

# DW-1009 Replication Lag Exceeded Threshold dependency context

Dependency context for troubleshooting DW-1009.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
