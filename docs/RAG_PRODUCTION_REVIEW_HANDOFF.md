# Production RAG review handoff

## Status

Production RAG activation remains blocked. The active Markdown corpus under
`backend/rag` is intentionally empty, while 167 unverified documents remain in
`backend/rag-quarantine`. This handoff does not assert approval and does not make
any quarantined content retrievable.

An accountable service owner and a RAG governance approver must review at least
one candidate before either production deployment workflow can pass its hard
production-readiness gate. Pull-request CI reports this state as a warning so
code repairs can be integrated without claiming that the corpus is deployable.

## Initial review set

| Candidate | Proposed scope | Existing owner claim | Required subject-matter review | Main safety concern |
| --- | --- | --- | --- | --- |
| `backend/rag-quarantine/runbooks/catalog-cache-stale-runbook.md` | `catalog-api` | `commerce-ops` | Catalog/cache owner | Cache draining and key flush can amplify load or remove valid data. |
| `backend/rag-quarantine/runbooks/auth-session-store-hotspot-runbook.md` | `auth-session` | `identity-ops` | Identity/session owner | Shard rebalance and write redirection can disrupt active sessions. |
| `backend/rag-quarantine/runbooks/orders-replica-lag-runbook.md` | `orders-db` | `platform-ops` | Database and orders owners | Database failover needs explicit preconditions, data-safety checks, rollback, and approval policy. |
| `backend/rag-quarantine/runbooks/payments-webhook-retry-storm-runbook.md` | `payments-webhook` | `payments-ops` | Payments owner | Retry throttling can delay transactions and change delivery guarantees. |
| `backend/rag-quarantine/onboarding/prometheus-mysql-monitoring-onboarding.md` | `api-gateway`, `monitoring-adapter`, `mysql` | `platform-ops` | Observability and database owners | Endpoint, routing, and escalation claims must match the deployed environment. |

The owner values above are unverified claims copied from quarantined front
matter. They are not proof that the named team reviewed or owns the document.

## Required content review

For a selected candidate, the reviewer must verify the document against the
current production service and source record, then record:

- the intended tenant scope (`global` only with explicit administrator
  authorization, otherwise the exact tenant ID);
- the authoritative owner team and source system/reference;
- safe preconditions, permissions, blast-radius limits, and approval points;
- commands or actions with concrete parameters rather than generic placeholders;
- validation signals, rollback steps, escalation conditions, and expected
  recovery time;
- the exact supported service names and current deployment topology;
- removal of obsolete, demo-only, generated, or unverifiable statements.

The four runbook candidates are not ready as written. Their remediation sections
name potentially destructive actions without sufficient preconditions, bounded
execution steps, or service-specific validation. The onboarding candidate is a
lower-risk first option, but its routing and ownership claims still require
environment verification.

## Required governance metadata

After content review, the promoted Markdown document must include all fields
enforced by `RagGovernanceMetadata`:

- `kind`, `title`, `tenant_scope`, `services`, `owner_team`, `source_system`,
  and `source_ref`;
- `review_status`, `corpus_classification`, and `content_version`;
- `created_at`, `updated_at`, and `content_checksum`;
- `last_reviewed`, `reviewed_by`, `approved_by`, and `approved_at` when approved.

The checksum must be calculated from the final document body using the repository
checksum implementation. A globally scoped approved document must be classified
`PRODUCTION_CURATED`; a tenant-scoped approved document must be classified
`TENANT_CURATED`. Approval identity and timestamps must represent a real review,
not CI or synthetic placeholder values.

## Promotion procedure

1. Copy one reviewed candidate from `backend/rag-quarantine` to the appropriate
   content directory under `backend/rag`; keep the quarantine source for audit
   history unless the governance owner directs otherwise.
2. Rewrite and complete its content based on the subject-matter review.
3. Add the complete governance metadata and calculate the final body checksum.
4. Obtain approval from the accountable service owner and governance approver,
   recording their identities and approval time in the document metadata.
5. Run:

   ```text
   uv run python scripts/validate-rag-metadata.py --rag-root backend/rag --strict
   uv run python scripts/validate-rag-metadata.py --rag-root backend/rag --require-production-ready
   uv run pytest backend/tests/test_rag_governance.py backend/tests/test_rag_ingestion.py
   ```

6. Re-run the complete required CI workflow and keep the pull request in draft
   until every required check and credentialed staging validation passes.

## Reviewer decision record

Before promotion, attach or record the following in the pull request:

- selected candidate and final destination;
- tenant scope and whether global authorization was granted;
- service-owner reviewer name and decision;
- governance approver name and decision;
- source record verified and verification date;
- safety, rollback, and staging evidence reviewed;
- any expiration or mandatory next-review date.

Until that record exists, the correct system state is an empty production corpus,
a visible pull-request warning, and production deployments blocked by the
non-empty production RAG readiness gate.
