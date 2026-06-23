alert_id: DW-1001
alert_name: ETL Job Failure
service: airflow
severity: critical
alert_type: etl_failure

# ETL Job Failure (DW-1001)

Service: airflow
Severity: CRITICAL
Alert type: etl_failure

## Description
Scheduled ETL workflow failed before successful completion.

## Symptoms
- DAG failed
- Downstream jobs not triggered
- Missing daily data load

## Probable Root Causes
- Source database unavailable
- SQL query failure
- Network timeout
- Invalid credentials

## Investigation
1. Check Airflow DAG logs
1. Verify source connectivity
1. Validate credentials
1. Review recent code changes

## Remediation
- Retry failed task
- Fix source connectivity
- Correct SQL logic
- Re-run workflow

## Automation
- airflow dags trigger sales_etl

## RAG/SOP Notes
- This document was derived from RAG_doc.docx and is intended for retrieval, SOPs, and runbook-driven operations.
