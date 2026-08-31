# KaiOps Execution Catalog Update Process

This folder is the governed execution catalog used by orchestration and remediation planning.

## Files

- `playbooks.json`: maps alert families to ordered diagnostic, remediation, and validation steps.
- `action_catalog.json`: defines executable action IDs, operations, safety posture, commands, rollback, and expected evidence.
- `connectors.json`: maps services to connection profiles and allowed operations.

## Required Process For New Alert Types

1. Add or confirm a playbook in `playbooks.json`.
   - Match on service, alert type, and alert keywords.
   - Include at least one diagnostic step and one validation step.
   - Include remediation steps only when there is a safe action and rollback path.

2. Add missing actions in `action_catalog.json`.
   - Every action needs an `operation`, `command`, `safety`, and `expected_evidence`.
   - Mutating actions must include `approval_required: true`.
   - Mutating actions must include `rollback`.

3. Add or update the service connector in `connectors.json`.
   - `allowed_operations` must include each operation referenced by matched playbook actions.
   - Live execution requires a real `secret_ref` and connector executor.
   - Keep `dry_run_default` enabled unless a production change record approves live execution.

4. Add or update the alert knowledge document.
   - Include alert name, service, environment, signal, investigation, remediation script, rollback, and validation checks.
   - Prefer one guarded script over loose command/query fragments.

5. Validate the catalog.

```powershell
python scripts/validate_execution_catalog.py
```

6. Test with a representative alert.
   - Run the selected alert through onboarding/rule generation if needed.
   - Verify Processing Flow shows the matched playbook, connector, actions, fallback, and closure state.
   - Verify Flow Timeline includes the bus topics and service stages.

## Safety Rules

- Read-only diagnostics can run without approval if the connector is configured.
- Restart, scale, rollback, archive, failover, replay, and retry actions require approval.
- Remediation Engine must skip live execution when connector executor or `secret_ref` is missing.
- Approval users must be able to edit scripts, commands, queries, rollback, and validation checks before execution.

