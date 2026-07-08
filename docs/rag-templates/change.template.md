kind: change
title: <change title>
services: <service1>, <service2>
deployment: <deployment/version>
change_id: <CHG-XXXX>
source_system: <servicenow|jira|github|other>
source_ref: <change URL or ID>
risk_level: <low|medium|high>
rollout_window: <YYYY-MM-DD HH:MM TZ>

# <Change Title>

## Summary
Describe what changed.

## Scope
- Components touched
- Services affected

## Risk Assessment
- Primary risk
- Secondary risk

## Expected Signals
- Metrics/alerts expected after rollout

## Rollback Criteria
- Condition 1
- Condition 2

## Rollback Plan
1. Step one
2. Step two

## Post-Change Validation
- Health checks
- Business KPI checks
