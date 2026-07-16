kind: deployment
title: HighNetworkPacketLoss Deployment Guidance
alert_id: 0669dbc6-d12e-4ec5-b6ed-2bc1eaa06d4f
alert_type: HighNetworkPacketLoss
severity: critical
services: blackbox
root_cause: Deployment 2.5
impact: Blackbox service impact requires immediate triage
recommended_action: Rollback deployment

# HighNetworkPacketLoss Deployment Guidance

## Summary
Deployment guardrails and rollback checks for blackbox.

## Description
Alert HighNetworkPacketLoss observed on blackbox with severity CRITICAL.

Pre-deploy checks: SLO burn rate, dependency readiness, and database migration safety.

Post-deploy checks: p95 latency, error budget consumption, and alert noise monitoring for 30m.

Rollback criteria: sustained critical alerts for 10m or failed synthetic checks.

## Root Cause
Deployment 2.5

## Impact
Blackbox service impact requires immediate triage
