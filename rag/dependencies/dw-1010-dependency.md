kind: dependency
title: DW-1010 dependency context
services: customer-ingestion
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: DW-1010
last_reviewed: 2026-07-08

# DW-1010 Schema Drift Detected dependency context

Dependency context for troubleshooting DW-1010.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
