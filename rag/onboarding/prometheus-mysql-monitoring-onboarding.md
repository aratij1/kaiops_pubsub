kind: onboarding
title: Prometheus and MySQL monitoring onboarding readiness
services: api-gateway, monitoring-adapter, mysql
owner_team: platform-ops
last_reviewed: 2026-07-10
source_system: internal
source_ref: ONBOARDING-PROMETHEUS-MYSQL-LANDING-PAD

# Prometheus and MySQL monitoring onboarding readiness

Readiness checks for routing Prometheus + MySQL alerts into KaiOps landing pad.

## Required readiness

- Prometheus scraping enabled for KaiOps `/metrics` endpoints.
- MySQL exporter configured and healthy.
- Alertmanager webhook configured to `monitoring-adapter /alerts/alertmanager`.
- Monitoring adapter can publish `raw-alerts`.
- Alert stream in UI is reachable and rendering current alerts.

## Ownership and escalation

- Primary owner: platform-ops
- Escalation: database and reliability engineering teams
