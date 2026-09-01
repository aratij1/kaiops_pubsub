# Cloud operations Phase 3 — plan compiler and simulation

Date: 2026-08-21 (Asia/Calcutta)

## Outcome

Phase 3 adds a tenant-scoped, immutable plan compiler and a persisted dry-run simulation workflow to the cloud operations control plane. It intentionally performs no provider write operations.

## Delivered

- Canonical action-plan contracts with SHA-256 plan identity
- Compilation validation against governed service inventory and declared remediation capabilities
- Idempotent compilation: identical canonical input reuses the stored plan
- Risk and approval classification, with production always requiring approval
- Persisted simulation results and individual safety-gate evidence
- Tenant-scoped plan lookup and simulation
- Cloud audit events and versioned cloud-operation events for compilation and simulation
- API gateway administrator routes
- Operations cockpit controls for compiling and dry-running a plan
- MySQL migration for compiled plans and simulation records

## Safety properties

Simulation evaluates immutable identity, current service readiness, current target scope, rollback coverage, and human approval. A failed gate produces a `blocked` verdict. Simulation never invokes a provider connector or mutates a discovered resource.

Compiled plans cannot target resources outside the tenant/project/service/environment scope and cannot use actions absent from the service onboarding profile's remediation capabilities.

## Verification

- Python compilation: passed
- Focused cloud operations tests: 6 passed
- Frontend typecheck: passed
- Frontend unit tests: 62 passed in the suite; one worker-start timeout was rerun in isolation and its 2 tests passed

## Database changes

Migration `20260826_cloud_plan_compiler_phase3.sql` creates:

- `cloud_compiled_plans`
- `cloud_plan_simulations`

Both stores are explicitly tenant scoped. Plan checksum is unique to prevent duplicate immutable plans.

## Rollback

1. Remove the Phase 3 cloud service and API gateway plan routes.
2. Remove the cockpit plan compiler controls and client functions.
3. Remove the Phase 3 model/repository contracts and tests.
4. Drop `cloud_plan_simulations`, then `cloud_compiled_plans`, if persisted Phase 3 data is no longer required.

Rollback does not affect Phase 1 connections/discovery or Phase 2 onboarding/readiness data.

## Recommended Phase 4

Add explicit approval binding to the immutable checksum, provider-specific execution adapters, idempotent execution leases, rollback orchestration, and post-action validation. Keep execution disabled until every required simulation and approval gate is satisfied.
