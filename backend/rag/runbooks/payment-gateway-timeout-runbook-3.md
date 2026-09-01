kind: runbook
title: Payment Gateway Timeout Runbook
tenant_scope: default
services: payment-service
owner_team: payments-platform
source_system: kaiops.rag
source_ref: rag://default/runbook/payment-gateway-timeout-runbook
review_status: approved
corpus_classification: TENANT_CURATED
content_version: 1
created_at: 2026-08-31T13:05:29.974946+00:00
updated_at: 2026-08-31T13:05:29.963632+00:00
last_reviewed: 2026-08-31T13:05:29.963632+00:00
reviewed_by: unknown@kaiops.example.com
approved_by: unknown@kaiops.example.com
approved_at: 2026-08-31T13:05:29.963632+00:00
content_checksum: sha256:a4fad638d239ff1dda6afa92bfa3a239379ba152bdcba1a5de3badc25269d610

# Payment Gateway Timeout Runbook

## Description
# Payment Gateway Timeout Runbook

When payment-service encounters 504 timeouts, restart payment gateway pods and scale deployment.
