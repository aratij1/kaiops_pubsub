# Azure VM validation — 2026-08-20

Target: `kaims-dev` (`20.193.131.47`)
Access: read-only SSH as `azureuser` using the existing deployment key

No code was uploaded, no service was restarted, no configuration or secret value was read, and no database mutation was performed.

## Results

- SSH, Docker 29.6.1, and Docker Compose 5.3.1: available.
- Deployment directory `~/kaiops_pubsub` and non-empty `.env`: present.
- Root filesystem: 247 GiB total, 144 GiB used, 104 GiB available (59% used).
- Memory: 31 GiB total, approximately 14 GiB available; no swap configured.
- Compose services: running; the health-enabled critical services report healthy.
- Unhealthy or restarting containers: none.
- HTTP probes returned 200 for UI, UI-to-gateway proxy, API gateway, monitoring adapter, approval service, and remediation engine.
- Deployed `docker-compose.yml` timestamp: `2026-08-20 04:37:39 UTC`.

## Outstanding gates

- Production has 24 migrations and does not yet contain candidates `20260821`–`20260823`.
- Two `approval_capacity` rows still use the legacy `default` tenant and must be assigned to verified tenant IDs.
- All five rows in the production `users` table also use `default`, so the correct reviewer tenant assignments cannot be inferred from current production identity data.
- A database restore point cannot be verified through VM SSH alone.
- Azure control-plane checks (subscription/resource group, NSG, managed identity, Key Vault, snapshot/backup, and rollback) still require Azure CLI or portal evidence.
- The second documented VM, `20.69.233.125`, does not accept this PEM key and was not validated.

Decision: **VM runtime healthy; migration/deployment remains NO-GO until the outstanding gates are cleared.**

## Tenant cutover and backup update

The release owner selected a narrow seven-record identity cutover to `dgsl-dev`. Exactly five user rows and two approval-capacity rows were updated in one transaction and verified. Existing operational records and sessions remain on their prior tenant values by explicit scope choice.

A targeted pre-cutover backup and a full pre-migration logical backup were created, permission-restricted, gzip-tested, and checksummed. The checksum-verified three-file release bundle was uploaded to an isolated directory. Its production dry run reports exactly the expected three pending migrations and made no database change.

After explicit release-owner authorization, all three migrations were applied in order. Post-migration verification reports 27 applied migrations with nothing pending, the expected tables/columns/indexes, zero duplicate groups, and successful critical service health probes.

## Complete application deployment

After explicit release-owner authorization, the curated source archive was uploaded with the production `.env` preserved. Runtime state, generated RAG review output, ingested alerts, Playwright output, caches, dependencies, and local environment files were excluded by the deployment archive policy.

- Rollback baseline: `/home/azureuser/kaiops_backups/deployment/20260820T152603Z`, containing checksummed Compose state and the image IDs for all 43 previously running containers.
- All 18 application images built successfully; the UI production build and bundle-budget check passed during the image build.
- Compose replaced the application containers without stopping the stateful stack first.
- All active production services are running; no active container is unhealthy or restarting.
- Post-deployment probes for UI, gateway, monitoring, approval, and remediation returned 200 immediately and after the stability window.
- UI assets served by production match the new build fingerprints, including `index-DOv4fUWp.js` and `index-0-GDx6rU.css`.
- Eight critical application containers reported zero restarts after the stability window.
- Migration and tenant invariants remain intact: 27 migrations, five `dgsl-dev` users, two `dgsl-dev` capacity rows, and zero legacy identity/capacity defaults.
- Recent critical-service logs contained no traceback, fatal, panic, unhandled, or migration-failure signatures.
- The historical processed-result alert ID is not present on this VM and correctly returned 404 rather than the former schema-related 500.

Deployment status: **new Azure VM production build applied and verified.**

## Incident View details hotfix

Production inspection found that all legacy incident projections lack a canonical `alert_id`. The existing fallback changed the URL to `/incidents?incident_id=...`, but the route ignored that query and continued rendering the inbox. The UI now treats that URL as durable detail state, focuses the selected incident, opens its evidence workspace, and exposes a Back to inbox control. The UI-only image was rebuilt and deployed; its container is healthy with zero restarts, UI and gateway probes return 200, and the production-shaped Playwright regression passes.

The final guided-cockpit correction enriches legacy projections at read time from the immutable `incident_events.alert_id` relationship. All 24,262 production incidents have that relationship. A live incident resolved to an existing alert and its processed-result endpoint returned 200, so View details now enters the standard guided Incident Cockpit.

## Local-to-Azure parity

- Maintained runtime/build source: 248 local files and 248 Azure files; zero missing, extra, or checksum-different files.
- Eighteen stale pre-refactor source files and six editor backup/reject artifacts left by historical overlay deployments were removed from the remote source tree. Running containers and persistent data were not affected.
- Compose topology: 26 local services and 26 Azure services; zero differences.
- Azure-specific runtime keys are present without exposing their values.
- All 43 active containers are running.
- Database migration ledger remains at 27.

Parity status: **Azure code and topology match local exactly; only environment-specific configuration and persistent production data intentionally differ.**
