# Autonomous Operations Phase 8 — Artifact Security and Retention

Date: 2026-08-21 (Asia/Calcutta)

## Outcome

Phase 8 adds tenant ownership, retention metadata, signed provenance verification, and bounded
draft-pull-request authorization to evaluation and review artifacts. It does not add a source-control
provider adapter or any merge, deployment, patch-application, or preventive mutation capability.

## Delivered

- Additive evaluation-record columns for `tenant_id`, `expires_at`, and `artifact_signature`.
- Tenant-scoped evaluation lookup and listing in the shared repository.
- Evaluation creation assigns bounded retention between 7 days and 7 years, defaulting to 90 days.
- Authenticated gateway evaluation routes inject the caller's tenant and do not accept caller-selected
  tenant scope.
- HMAC-SHA256 artifact provenance with payload digest, signer key ID, signing time, and expiry.
- Constant-time provenance signature comparison and expiry enforcement.
- A short-lived draft-pull-request authorization contract limited to Administrator and L3 Engineer
  roles and the exact patch proposal, repository, revision, and provider connection.

## Migration

Apply `20260831_evaluation_tenant_retention.sql`. Existing rows are explicitly assigned to the
`default` tenant and remain isolated from named tenants. New writes persist their verified tenant.

## Safety properties

- Cross-tenant evaluation reads return no record.
- Gateway routes require authenticated access under the evaluation route policy.
- Artifact provenance is invalid after expiry or when verified with the wrong key.
- Draft-PR authorization expires within 15 minutes.
- Draft-PR authorization structurally sets merge and deployment authorization to false.
- No provider API call or repository mutation is implemented in this phase.

## Verification

- Focused artifact, tenant, evaluation persistence/API, and gateway tests: 52 passed.
- Changed Python modules: compilation passed.
- Focused diff whitespace validation: passed.

## Recommended next increment

Add a retention sweeper with audited deletion, key-rotation support, and a provider adapter that can
create only a draft pull request after verifying tenant, provenance, unexpired authorization, exact
base revision, and repository scope. Keep merge, deployment, and branch deletion unavailable.
