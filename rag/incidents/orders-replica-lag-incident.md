alert_id: ORDERS-REPLICA-LAG
alert_name: Orders database replica lag
service: orders-db
severity: critical
alert_type: incident
source_system: internal
source_ref: INC-NEW
resolved_by: platform-ops
closed_at: 2026-07-08

# Orders database replica lag

## Summary
Replica lag above threshold for 10 minutes

## Root Cause
Primary write saturation

## Impact
Stale reads on order queries

## Remediation
Failover database
