alert_id: DW-1018
alert_name: Data Pipeline Backlog Growing
service: data-pipeline
severity: high
alert_type: backlog

# Data Pipeline Backlog Growing (DW-1018)

Service: data-pipeline
Severity: HIGH
Alert type: backlog

## Description
Data pipeline backlog is growing and records are not being processed quickly enough.

## Symptoms
- Queue depth increasing
- Lagging freshness
- Worker saturation

## Probable Root Causes
- Slow processing
- Increased ingestion volume

## Investigation
1. Check backlog growth rate
1. Inspect worker throughput
1. Review ingestion spikes

## Remediation
- Scale processing cluster
- Increase worker nodes

## Automation
- Scale processing cluster

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
