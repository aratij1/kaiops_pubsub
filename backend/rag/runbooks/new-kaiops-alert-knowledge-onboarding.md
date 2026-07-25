kind: runbook
title: new_kaiops Alert Knowledge Onboarding
alert_type: configuration
severity: high
services: new_kaiops
recommended_action: Review generated draft and finalize onboarding knowledge.

# new_kaiops Alert Knowledge Onboarding

## Summary
Auto-generated from 1 uploaded source document(s).

## Description
Auto-generated alert onboarding for new_kaiops.

Source evidence:
- [Service Knowledge] new_kaiops-prompt-service-knowledge.md: # KaiOpsMySQLAlertsTableRowsHigh Knowledge And Remediation Guide Kind: runbook Alert: KaiOpsMySQLAlertsTableRowsHigh Service: mysql Environment: prod Severity: warning Source alert file: 20260721T081108745158Z_kaiopsmysq

Derived requirements:
- KaiOpsMySQLAlertsTableRowsHigh Knowledge And Remediation Guide
- Alert: KaiOpsMySQLAlertsTableRowsHigh
- Source alert file: 20260721T081108745158Z_kaiopsmysqlalertstablerowshigh_46e408884901f001.json
- Prometheus alert `KaiOpsMySQLAlertsTableRowsHigh` fires when
- `kaiops_mysql_alerts_table_rows{database="kaiops",table="alerts"}` is above the configured threshold.
- The affected connector is `kaiops-mysql`; the affected database is `kaiops`; the affected table is `alerts`.

Use this draft to refine final triage and remediation guidance.
