kind: dependency
title: DW-1003 dependency context
services: oracle-source
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1003
last_reviewed: 2026-07-08

# DW-1003 Source System Unavailable dependency context

Dependency context for troubleshooting DW-1003.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
