alert_id: DW-1009
alert_name: Replication Lag Exceeded Threshold
service: replication-service
severity: high
alert_type: replication

# Replication Lag Exceeded Threshold (DW-1009)

Service: replication-service
Severity: HIGH
Alert type: replication

## Description
Replication lag exceeded the threshold and replica data is stale.

## Symptoms
- Replica lag growing
- Reads returning stale data
- Replication alerts firing

## Probable Root Causes
- Network latency
- Replication process slowdown

## Investigation
1. Check replication health
1. Verify network latency
1. Inspect replication process metrics

## Remediation
- Restart replication service
- Increase replication bandwidth

## Automation
- Restart replication service

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
