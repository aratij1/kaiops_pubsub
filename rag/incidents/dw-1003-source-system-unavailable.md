alert_id: DW-1003
alert_name: Source System Unavailable
service: oracle-source
severity: critical
alert_type: source_connectivity

# Source System Unavailable (DW-1003)

Service: oracle-source
Severity: CRITICAL
Alert type: source_connectivity

## Description
Source system is unavailable or cannot be reached from the ingestion layer.

## Symptoms
- Connection errors
- No new source records
- Repeated retry failures

## Probable Root Causes
- Oracle outage
- Network issue
- Firewall blockage

## Investigation
1. Verify source status page
1. Check listener/service health
1. Confirm firewall and routing rules

## Remediation
- Verify database status
- Restart listener
- Restore connectivity

## Automation
- Run source connectivity probe

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
