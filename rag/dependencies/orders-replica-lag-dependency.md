kind: dependency
title: ORDERS-REPLICA-LAG dependency context
services: orders-db
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: INC-NEW
last_reviewed: 2026-07-08

# Orders database replica lag dependency context

## Expected Dependency Checks
- Upstream availability
- Downstream consumer health
- Network and broker path status
