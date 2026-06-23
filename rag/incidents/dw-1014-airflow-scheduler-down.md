alert_id: DW-1014
alert_name: Airflow Scheduler Down
service: airflow
severity: critical
alert_type: scheduler

# Airflow Scheduler Down (DW-1014)

Service: airflow
Severity: CRITICAL
Alert type: scheduler

## Description
Workflow scheduler is unavailable and orchestration is paused.

## Symptoms
- No DAG scheduling
- Pending jobs not starting
- Scheduler alerts

## Probable Root Causes
- Scheduler process crash
- Resource exhaustion

## Investigation
1. Check scheduler process status
1. Inspect resource usage
1. Review scheduler logs

## Remediation
- Restart scheduler
- Verify scheduler health

## Automation
- systemctl restart airflow-scheduler

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
