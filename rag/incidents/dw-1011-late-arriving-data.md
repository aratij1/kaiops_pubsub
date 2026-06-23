alert_id: DW-1011
alert_name: Late Arriving Data
service: transaction-feed
severity: medium
alert_type: data_latency

# Late Arriving Data (DW-1011)

Service: transaction-feed
Severity: MEDIUM
Alert type: data_latency

## Description
Data arrived later than expected from the source feed.

## Symptoms
- Late-arriving records
- Downstream jobs waiting
- Freshness breach

## Probable Root Causes
- Delayed source feed
- Batch scheduling issue

## Investigation
1. Check source feed schedule
1. Review batch timing
1. Confirm delay on upstream systems

## Remediation
- Execute incremental load
- Notify source owners

## Automation
- Execute incremental load

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
