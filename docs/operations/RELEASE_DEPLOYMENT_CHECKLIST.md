# KaiOps release and deployment checklist

Use this checklist for every production promotion. A checked repository-level item is not evidence that an Azure resource was validated; attach command output and identify the tenant/subscription for every environment check.

## Source and artifacts

- [ ] Review `git status --porcelain=v1 -uall` and assign every tracked change to the release.
- [ ] Exclude generated Playwright output, screenshots, traces, local runtime files, and RAG review output unless each file is intentionally curated.
- [ ] Scan user-visible source for mojibake (`Â`, `â€¦`, `â†`, `â€”`, `Ã`).
- [ ] Pin container images by immutable tag or digest; no `:latest` and no `REPLACE` values.
- [ ] Obtain approval for the exact staged diff before commit or push.

## Test gates

- [ ] Production frontend build and bundle budget pass.
- [ ] Complete Playwright suite passes, including incident detail, approval, remediation, rollback, accessibility, and long-duration layout stability.
- [ ] Complete `backend/tests` suite passes using an explicit writable `--basetemp` on Windows.
- [ ] Tenant isolation tests pass for two distinct verified identities.
- [ ] A production-like smoke incident completes without bypassing approval or plan binding.

## Azure preflight

- [ ] Azure CLI and Bicep are installed; `az account show` identifies the intended subscription and tenant.
- [ ] `scripts/validate_aca_parameters.py` passes without `--allow-placeholders`.
- [ ] `az bicep build` and resource-group deployment validation/what-if pass.
- [ ] Key Vault references exist and the managed identity can read them; no secret values appear in source, logs, or deployment history.
- [ ] ACR pull, Service Bus topics/subscriptions, Blob storage, MySQL, Temporal, OTLP, DNS/TLS, and private network paths are reachable from the Container Apps environment.
- [ ] OIDC issuer, audience, client ID, PKCE callbacks, and role claims are verified with at least two real tenant identities.

## Database and rollout

- [ ] Back up the production database and record the restore point.
- [ ] Review all pending migrations in filename order. Migrations must be backward-compatible because the runner is forward-only.
- [ ] Run `scripts/apply-migrations.py --dry-run`, approve the list, then apply once.
- [ ] Deploy with multiple revisions, keep the known-good revision active, and shift traffic gradually.
- [ ] Verify health probes, traces, error rate, queue age, approval latency, and incident lifecycle state.

## Rollback rehearsal

- [ ] Record the known-good revision for every Container App.
- [ ] Rehearse setting 100% traffic back to those revisions in a non-production environment.
- [ ] Confirm the older revision works with the migrated schema.
- [ ] Stop new remediation dispatch, preserve Temporal/action idempotency state, and drain or quarantine unsafe messages.
- [ ] Capture evidence before deactivating a failed revision; restore the database only through the approved restore procedure.

## Approval record

- Release/version:
- Commit/digest:
- Azure tenant/subscription/resource group:
- Test evidence location:
- Migration backup/restore point:
- Known-good revisions:
- Engineering approver:
- SRE/change approver:
- Decision and timestamp:
