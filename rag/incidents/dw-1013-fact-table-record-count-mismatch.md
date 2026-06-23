alert_id: DW-1013
alert_name: Fact Table Record Count Mismatch
service: sales-fact
severity: critical
alert_type: reconciliation

# Fact Table Record Count Mismatch (DW-1013)

Service: sales-fact
Severity: CRITICAL
Alert type: reconciliation

## Description
Fact table counts do not match the expected source totals.

## Symptoms
- Count mismatch
- Reconciliation failures
- Partial load indicators

## Probable Root Causes
- Partial load
- Duplicate processing
- Source extraction issue

## Investigation
1. Perform reconciliation
1. Review source extraction
1. Identify duplicates or skipped partitions

## Remediation
- Perform reconciliation
- Reload affected partition

## Automation
- Reload affected partition

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
