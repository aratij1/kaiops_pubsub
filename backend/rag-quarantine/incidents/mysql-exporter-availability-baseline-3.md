kind: incident
title: MySQL Exporter Availability Baseline
alert_type: database
severity: critical
services: mysql, mysql-exporter

# MySQL Exporter Availability Baseline

## Summary
Real Prometheus-based MySQL exporter and DB signal monitoring

## Description
If mysql-exporter is down or MySQL connection pressure rises, validate exporter container, credential config, target scrape status, and DB connection limits to restore telemetry and service safety.
