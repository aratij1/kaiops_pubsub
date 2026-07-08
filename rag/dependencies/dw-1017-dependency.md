kind: dependency
title: DW-1017 dependency context
services: daily-sales-report
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1017
last_reviewed: 2026-07-08

# DW-1017 Business SLA Missed dependency context

Dependency context for troubleshooting DW-1017.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
