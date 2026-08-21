# KaiOps production-hardening baseline

Date: 2026-08-21 (Asia/Calcutta)

## Repository identity

- Selected branch: `fix/kaims-resolution-production-readiness`
- Commit: `7ebf747d137e1f55af303fa681a9f0e0132a87c8`
- Upstream after `git fetch --all --prune`: same commit
- Tracked working-tree changes: 262
- Untracked/generated entries: approximately 7,400, dominated by runtime RAG review evidence and browser artifacts

The existing working tree predates this hardening phase and is preserved. Reviewable commits must select only phase-owned files.

## Deployment baseline

`docker compose up -d --build` completed successfully. The UI image production build and bundle budget passed. Core infrastructure was healthy; newly recreated API, context, resolution, and remediation containers were still inside their startup-health grace period at the first status capture.

## Test baseline

- Backend: 585 passed with workspace `--basetemp`
- Initial host backend run: 543 passed and 42 setup errors caused only by an inaccessible Windows pytest temp directory
- Frontend unit tests: 58 assertions passed; two JSDOM worker processes repeatedly failed to start under the resource load of the deployed stack
- Frontend production build and bundle budget: passed during Docker deployment
- Frontend typecheck: previously passed on the same working tree; the post-deployment isolated run became resource-stalled and was terminated
- Execution catalog: 29 actions, 11 connectors, 9 playbooks; zero errors
- Execution checksums: 9 valid; zero errors
- RAG metadata: 344 files, zero errors, three unknown-section warnings
- Focused tenant/security/closure/idempotency suite: 38 passed

## Failure matrix

| Failure | Service | Root cause | Classification | Proposed correction |
|---|---|---|---|---|
| 42 backend setup errors | Test runtime | Host temp root is inaccessible | Environment, not functional | Always set a workspace-owned pytest `--basetemp` in local/CI scripts |
| Design-system and ResolutionPanel workers fail to start | Frontend test runtime | Container worker startup timeout while full deployed stack consumes resources | Environment, tests pass in prior isolated runs | Add a resource-stable frontend test profile and run heavyweight DOM files in isolated shards |
| Manual close accepts `closed_by` from body | Gateway/closure | Identity is client controlled and closure endpoint is directly callable | Functional security defect | Derive tenant/role/operator at gateway and require service authentication downstream |
| Manual close asserts restored health and cleared alerts | Closure | Administrative disposition is conflated with technical recovery | Functional correctness defect | Persist manual closure separately with both technical recovery flags false |
| Closure lifecycle contains fallback `default` tenants | Closure/common lifecycle | Legacy reconstruction silently invents tenant identity | Functional tenant-isolation defect | Require canonical action/incident/report tenant and reject missing/mismatched identity |
| Approval service has direct host ingress | Compose/network boundary | Port is published and no service authentication boundary protects all reads/writes | Functional security defect | Remove public port, add internal authentication, gateway-only access and NetworkPolicy |
| Validation accepts plan URLs | Closure validation | Execution plan can influence outbound targets | Functional SSRF/governance defect | Replace URLs with immutable onboarded typed validator references |

## Safety posture during hardening

HOTL execution, automatic incident closure, automatic runbook approval, generated-shell execution, and execution against unverified targets or credentials remain disabled/fail-closed until all production gates pass.
