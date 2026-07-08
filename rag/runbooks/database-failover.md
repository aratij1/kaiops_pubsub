kind: runbook
title: Orders database failover
services: orders-db, orders
owner_team: platform-ops
last_reviewed: 2026-07-08
source_system: internal
source_ref: RUNBOOK-DATABASE-FAILOVER

# Orders database failover

If orders database replica lag exceeds the read consistency threshold, reduce
traffic to lagging replicas and prepare failover when the primary is saturated.

Recommended remediation:

1. Confirm replica lag and write saturation.
2. Put read replicas in degraded mode.
3. Fail over to a healthy database node when approved.
4. Validate stale reads are resolved and alerts clear.
