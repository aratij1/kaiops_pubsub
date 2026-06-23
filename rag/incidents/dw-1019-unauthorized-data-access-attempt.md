alert_id: DW-1019
alert_name: Unauthorized Data Access Attempt
service: data-warehouse
severity: critical
alert_type: security

# Unauthorized Data Access Attempt (DW-1019)

Service: data-warehouse
Severity: CRITICAL
Alert type: security

## Description
Unauthorized access was attempted against warehouse data or controls.

## Symptoms
- Suspicious access logs
- Policy violations
- Unexpected account activity

## Probable Root Causes
- Compromised account
- Misconfigured permissions

## Investigation
1. Review audit logs
1. Confirm account activity
1. Validate permission changes

## Remediation
- Lock account
- Rotate credentials
- Review audit logs

## Automation
- Disable affected user immediately

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
