kind: incident
title: KaiOps Service Health Baseline
alert_type: availability
severity: high
services: api-gateway, monitoring-adapter, orchestrator

# KaiOps Service Health Baseline

## Summary
Real Prometheus-based service health monitoring for KaiOps microservices

## Description
When KaiOps service targets go down or latency spikes, use this alert context to triage scrape health, gateway reachability, and service availability before remediation.
