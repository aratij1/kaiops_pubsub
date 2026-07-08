kind: dependency
title: DW-1016 dependency context
services: cdc-pipeline
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1016
last_reviewed: 2026-07-08

# DW-1016 Failed CDC Processing dependency context

Dependency context for troubleshooting DW-1016.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
