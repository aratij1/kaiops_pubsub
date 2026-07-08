kind: dependency
title: DW-1005 dependency context
services: dq-framework
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1005
last_reviewed: 2026-07-08

# DW-1005 Data Quality Check Failed dependency context

Dependency context for troubleshooting DW-1005.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
