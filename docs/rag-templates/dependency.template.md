kind: dependency
title: <dependency graph title>
services: <primary service>
dependencies: <dep1>, <dep2>, <dep3>
source_system: <cmdb|service-catalog|observability-map|other>
source_ref: <graph URL or ID>
last_reviewed: <YYYY-MM-DD>

# <Dependency Graph Title>

## Service Context
Describe the primary service and role.

## Upstream Dependencies
- Dependency A and why it matters
- Dependency B and failure impact

## Downstream Consumers
- Consumer A
- Consumer B

## Failure Propagation
- How latency/errors propagate
- Blast-radius indicators

## Critical Paths
- Path 1
- Path 2

## Operational Notes
- Known bottlenecks
- Isolation patterns
