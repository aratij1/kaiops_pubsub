alert_id: DW-1004
alert_name: Kafka Consumer Lag High
service: kafka-ingestion
severity: high
alert_type: streaming

# Kafka Consumer Lag High (DW-1004)

Service: kafka-ingestion
Severity: HIGH
Alert type: streaming

## Description
Streaming consumer lag is increasing and records are not being processed in time.

## Symptoms
- Consumer lag rising
- Records accumulating in queue
- Throughput decreasing

## Probable Root Causes
- Slow consumers
- High message volume
- Consumer crash

## Investigation
1. Inspect consumer lag metrics
1. Check consumer logs
1. Review partition balance

## Remediation
- Scale consumer group
- Restart consumers
- Increase partitions

## Automation
- kubectl scale deployment kafka-consumer --replicas=5

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
