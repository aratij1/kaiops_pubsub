kind: runbook
title: Orders database failover
services: orders-db, orders

# Orders database failover

If orders database replica lag exceeds the read consistency threshold, reduce
traffic to lagging replicas and prepare failover when the primary is saturated.

Recommended remediation:

1. Confirm replica lag and write saturation.
2. Put read replicas in degraded mode.
3. Fail over to a healthy database node when approved.
4. Validate stale reads are resolved and alerts clear.
