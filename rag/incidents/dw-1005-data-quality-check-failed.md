alert_id: DW-1005
alert_name: Data Quality Check Failed
service: dq-framework
severity: critical
alert_type: data_quality

# Data Quality Check Failed (DW-1005)

Service: dq-framework
Severity: CRITICAL
Alert type: data_quality

## Description
Data quality rules failed on the latest batch or ingestion pass.

## Symptoms
- Validation errors
- Unexpected nulls or duplicates
- Transformation mismatches

## Probable Root Causes
- Null values
- Duplicate records
- Invalid transformations

## Investigation
1. Identify bad records
1. Run validation scripts
1. Trace transformation outputs

## Remediation
- Identify bad records
- Run validation scripts
- Reprocess dataset

## Automation
- Run dq validation job

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
