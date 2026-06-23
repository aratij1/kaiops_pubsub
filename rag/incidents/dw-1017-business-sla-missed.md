alert_id: DW-1017
alert_name: Business SLA Missed
service: daily-sales-report
severity: critical
alert_type: sla_breach

# Business SLA Missed (DW-1017)

Service: daily-sales-report
Severity: CRITICAL
Alert type: sla_breach

## Description
Data was not delivered within the agreed SLA window.

## Symptoms
- Delivery delayed beyond SLA threshold
- Downstream consumers waiting on data

## Probable Root Causes
- Upstream delay
- Resource contention
- Failed dependency job

## Investigation
1. Review upstream job status
1. Check queue depth and worker utilization
1. Inspect dependency failures

## Remediation
- Trigger delayed pipeline
- Increase compute resources
- Escalate SLA breach

## Automation
- Trigger delayed pipeline job
- Scale workers if backlog continues

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
