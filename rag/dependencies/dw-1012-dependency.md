kind: dependency
title: DW-1012 dependency context
services: customer-dimension
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1012
last_reviewed: 2026-07-08

# DW-1012 Dimension Load Failure dependency context

Dependency context for troubleshooting DW-1012.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
