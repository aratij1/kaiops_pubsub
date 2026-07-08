kind: dependency
title: INC-9011 dependency context
services: orders-db
dependencies: cmdb, observability, message-bus
source_system: internal
source_ref: INC-9011
last_reviewed: 2026-07-08

# INC-9011 INC-9011 orders database replica lag dependency context

Dependency context for troubleshooting INC-9011.

## Expected Dependency Checks
- Upstream data/service availability
- Downstream consumer health
- Network and broker path health
