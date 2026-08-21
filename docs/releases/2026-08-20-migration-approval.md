# Migration approval record — 2026-08-20

## Candidate set

Apply in this order only:

1. `20260821_resolution_governance.sql` — SHA-256 `B4556F974C4CD8573CBF2CDEA48BD7A2AE58D96D92B695E1BA619B53F965954C`
2. `20260822_approval_plan_binding.sql` — SHA-256 `23F1E274EDEB309172D0CE8F358F80356E587AB03C8BF2840C292289B3E9753B`
3. `20260823_approval_capacity_tenant_scope.sql` — SHA-256 `A96432DC3E106EE2CCEDD8160618F1C569F39E3990D311FFCF661FBB9E040A6B`

Any checksum change invalidates this review and requires revalidation.

## Technical review

- `20260821` adds resolution-governance persistence required by the new workflow.
- `20260822` adds nullable approval plan-binding and expiry/role fields plus its lookup index. Its conditional DDL is compatible with MySQL 8.4 and safe to rerun.
- `20260823` replaces legacy global uniqueness with tenant-scoped uniqueness for approval capacity and assignments. Its conditional index operations are compatible with MySQL 8.4 and safe to rerun.
- The runner is forward-only. Application rollback must use a revision compatible with the expanded schema; database restoration is an explicit production restore operation, not an automatic down migration.

## Evidence

- Local MySQL 8.4 application: passed; `schema_migrations` contains 27 records and nothing remains pending.
- Duplicate precheck for `(tenant_id, username)` in `approval_capacity`: zero duplicate groups.
- Duplicate precheck for `(tenant_id, incident_id)` in `approval_assignments`: zero duplicate groups.
- Focused migration/approval regression tests: 16 passed.
- The previously failing processed-result request returned HTTP 200 after migration.

## Production approval gates

- [ ] Confirm the three production-file checksums exactly match this record.
- [ ] Record Azure tenant, subscription, resource group, database host, and change ticket.
- [ ] Take and verify a production restore point.
- [ ] Run the duplicate queries against production and attach zero-row output.
- [ ] Run `scripts/apply-migrations.py --dry-run`; it must list exactly these three files, in this order.
- [ ] Obtain engineering and SRE/change approvals.
- [ ] Apply once, verify all three `schema_migrations` records, then run approval and incident smoke tests.
- [ ] Keep the known-good application revision available and verify it tolerates the additive schema.

## Azure VM preflight — 2026-08-20

Target `kaims-dev` (`20.193.131.47`) was inspected read-only over SSH.

- The production migration ledger contains 24 entries; its latest entry is `20260820_resolution_investigations.sql`.
- The three candidate files and the explicit migration runner are not yet deployed to the VM.
- Both tenant-scoped duplicate queries returned zero groups.
- `approval_assignments` contains zero legacy `default`-tenant rows.
- `approval_capacity` contains **two** legacy `default`-tenant rows. These must be mapped to verified tenant IDs before `20260823` is authorized.
- Identity correlation found five production users, all still assigned to `default`; therefore no verified production tenant ID exists from which the two reviewer mappings can be safely inferred. Migration approval requires an authoritative tenant identifier and identity cutover first.
- None of the five `20260821` governance tables is present, consistent with the migration ledger.

### Cleared pre-application gates

- The authorized narrow cutover updated exactly five `users` and two `approval_capacity` rows from `default` to `dgsl-dev`; both tables now contain zero `default` rows.
- Targeted backup: `/home/azureuser/kaiops_backups/tenant-cutover/users-approval_capacity-before-dgsl-dev-20260820T151721Z.sql.gz`, SHA-256 `3807b3137ebdf61fb2f13fa2d929ac69db62eaadd70b8ccab1500e5b02f6b409`.
- Full pre-migration backup: `/home/azureuser/kaiops_backups/pre-migration/kaiops-before-20260821-23-20260820T151742Z.sql.gz`, SHA-256 `b4b6aed5f5628d18c58b43ad7a96b068c5a85dba0f2f02ddc8e87c818462aff6`.
- Both gzip archives passed integrity validation and are mode `0600` under mode `0700` backup directories.
- Uploaded candidate checksums match this approval record.
- Production dry run lists exactly `20260821`, `20260822`, and `20260823`, in order; no migration was applied by the dry run.

## Production execution result

The release owner explicitly authorized production DDL execution. The checksum-verified runner applied, in order:

1. `20260821_resolution_governance.sql`
2. `20260822_approval_plan_binding.sql`
3. `20260823_approval_capacity_tenant_scope.sql`

Post-application evidence:

- A second dry run reports 27 applied migrations and nothing pending.
- All three candidate filenames are present in `schema_migrations`.
- Five governance tables and four approval-binding columns are present.
- Both tenant-scoped unique indexes are present.
- Capacity and assignment duplicate-group counts are zero.
- MySQL, gateway, remediation engine, and UI health checks remain healthy; UI, gateway proxy, monitoring, approval, and remediation HTTP probes return 200.

Production migration status: **applied and verified successfully.**

Status: **technically approved for controlled environment validation; production execution not authorized.**

Engineering approver:

SRE/change approver:

Decision timestamp:
