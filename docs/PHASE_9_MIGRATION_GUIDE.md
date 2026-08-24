# Phase 9 Migration Guide

Phase 9 is additive and preserves legacy API identifiers where product renaming would introduce compatibility risk.

1. Back up MySQL and record the current image digests.
2. Apply migrations in filename order with `scripts/apply-migrations.py`; migrations add operational-twin provenance and the canonical two-role model without deleting legacy records.
3. Deploy shared backend code before services that emit new event fields. Canonical consumers accept legacy records during transition.
4. Configure only `secret_ref` values. Resolve secrets through the selected provider; never migrate raw credentials into payloads.
5. Deploy connector-hub, cloud-operations, and updated incident services with execution disabled.
6. Run deterministic discovery, verify stable identities and relationships, and recalculate readiness.
7. Map legacy roles to `ADMIN` or `HITL_APPROVER`; retain compatibility aliases until all stored assignments are migrated.
8. Enable capabilities individually after dry-run, rollback, validation, approval, and audit checks pass. Production autonomy remains disabled until mandatory readiness gates pass.
9. Deploy the UI last and run authenticated smoke, accessibility, and responsive checks.
10. Run `python scripts/validate_phase9_readiness.py`, CI, and the environment-specific load/integration suite before promotion.

Rollback application images first. Additive columns and event fields may remain while older code runs. Do not drop Phase 9 data until retention and audit requirements are satisfied. Disable connector execution and autonomy flags before any rollback involving governed actions.
