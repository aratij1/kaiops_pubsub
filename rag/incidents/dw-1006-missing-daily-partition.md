alert_id: DW-1006
alert_name: Missing Daily Partition
service: sales-fact-table
severity: high
alert_type: partition_missing

# Missing Daily Partition (DW-1006)

Service: sales-fact-table
Severity: HIGH
Alert type: partition_missing

## Description
Expected daily partition is missing from the warehouse table.

## Symptoms
- Partition absent
- Queries missing latest day
- Fresh load not visible

## Probable Root Causes
- ETL failure
- Partition creation job failed

## Investigation
1. Check partition creation workflow
1. Verify ingest completion
1. Inspect orchestration logs

## Remediation
- Backfill partition
- Re-run ingestion workflow

## Automation
- Backfill partition script

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
