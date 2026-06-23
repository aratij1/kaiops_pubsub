alert_id: DW-1008
alert_name: Query Performance Degradation
service: data-warehouse
severity: high
alert_type: performance

# Query Performance Degradation (DW-1008)

Service: data-warehouse
Severity: HIGH
Alert type: performance

## Description
Query execution time has degraded in the warehouse or reporting layer.

## Symptoms
- Longer dashboard load times
- Slow query execution
- Higher CPU/IO usage

## Probable Root Causes
- Missing indexes
- Poor execution plan
- Large table scans

## Investigation
1. Analyze query plan
1. Refresh statistics
1. Identify scans and joins

## Remediation
- Analyze query plan
- Refresh statistics
- Optimize SQL

## Automation
- Refresh warehouse stats

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
