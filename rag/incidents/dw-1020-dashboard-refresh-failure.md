alert_id: DW-1020
alert_name: Dashboard Refresh Failure
service: powerbi-reporting
severity: high
alert_type: reporting

# Dashboard Refresh Failure (DW-1020)

Service: powerbi-reporting
Severity: HIGH
Alert type: reporting

## Description
Dashboard refresh failed and reporting data is stale.

## Symptoms
- Refresh job failures
- Stale dashboard visuals
- Dataset timeout errors

## Probable Root Causes
- Warehouse unavailable
- Dataset refresh timeout

## Investigation
1. Check refresh job logs
1. Validate source connectivity
1. Review dataset timeout settings

## Remediation
- Restart refresh job
- Validate data source connectivity
- Re-run dashboard refresh

## Automation
- Restart refresh job

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
