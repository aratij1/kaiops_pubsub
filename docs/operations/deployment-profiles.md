# KaiMS deployment profiles

KaiMS defaults to the complete incident-management path without starting every
engineering tool. Lean mode retains ingestion, correlation, evidence collection,
RCA, model routing, orchestration, approval, remediation, closure, audit,
notification, periodic knowledge development, persistence, API, and UI.

| Profile | Services | Use |
|---|---:|---|
| `lean` (default) | 41 | Normal KaiMS operation, including complete automated application onboarding and its validation runtime |
| `observability` | 42 | Add Grafana visualization to the operational metrics runtime |
| `monitoring-authoring` | 41 | Compatibility alias; authoring workers now run in the default automated path |
| `evaluation` | 41 | Compatibility profile for environments that provide the evaluation service separately |
| `full` | 43 | Add all local engineering and administration diagnostics |

```powershell
.\scripts\start-kaims.ps1
.\scripts\start-kaims.ps1 -Profile observability
.\scripts\start-kaims.ps1 -Profile monitoring-authoring
.\scripts\start-kaims.ps1 -Profile full
```

Pass `-Build` only after dependency or source changes. Ordinary restarts reuse
existing images and avoid unnecessary CPU, memory, and registry work.

When switching from `full` to `lean`, the script stops only the known
profile-only containers; it does not perform project-wide orphan reconciliation.
Named data volumes are not deleted.

## Quality boundary

Lean mode does not bypass confidence, evidence, approval, policy, validation,
rollback, audit, continuous-learning controls, or application onboarding. The
discovery, metric validation, rule authoring, Prometheus configuration,
validation, and dashboard workers run with the onboarding API so registrations
cannot be accepted into an unconsumed workflow. Lean mode still excludes the
Grafana and auxiliary observability visualization, offline evaluation, and
Temporal's separate administration UI.
