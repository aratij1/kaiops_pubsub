alert_id: DW-1016
alert_name: Failed CDC Processing
service: cdc-pipeline
severity: critical
alert_type: change_data_capture

# Failed CDC Processing (DW-1016)

Service: cdc-pipeline
Severity: CRITICAL
Alert type: change_data_capture

## Description
CDC processing failed and transaction logs are not being consumed.

## Symptoms
- CDC pipeline stalled
- Transaction backlog grows
- Processing errors

## Probable Root Causes
- CDC connector failure
- Log corruption
- Source outage

## Investigation
1. Check CDC connector status
1. Inspect transaction logs
1. Verify source connectivity

## Remediation
- Restart CDC connector
- Reprocess transaction logs

## Automation
- Restart CDC connector

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
