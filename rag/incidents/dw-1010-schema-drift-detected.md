alert_id: DW-1010
alert_name: Schema Drift Detected
service: customer-ingestion
severity: critical
alert_type: schema_change

# Schema Drift Detected (DW-1010)

Service: customer-ingestion
Severity: CRITICAL
Alert type: schema_change

## Description
Schema drift was detected between source and warehouse ingestion mapping.

## Symptoms
- New fields not mapped
- Transformation errors
- Downstream type mismatches

## Probable Root Causes
- Source schema modification
- New columns added

## Investigation
1. Compare source and target schema
1. Review recent source changes
1. Check ingestion mapping versions

## Remediation
- Update ingestion mappings
- Regenerate schemas
- Validate transformations

## Automation
- Regenerate ingestion schemas

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
