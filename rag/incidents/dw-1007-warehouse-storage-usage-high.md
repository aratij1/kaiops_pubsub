alert_id: DW-1007
alert_name: Warehouse Storage Usage High
service: snowflake
severity: medium
alert_type: capacity

# Warehouse Storage Usage High (DW-1007)

Service: snowflake
Severity: MEDIUM
Alert type: capacity

## Description
Warehouse storage usage is approaching or above capacity thresholds.

## Symptoms
- Storage alerts firing
- Slower maintenance operations

## Probable Root Causes
- Data growth
- Stale historical data

## Investigation
1. Review storage trends
1. Find stale tables and partitions
1. Check retention policy

## Remediation
- Purge unused tables
- Archive old partitions
- Increase storage quota

## Automation
- Archive old partitions job

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
