# KaiMS deployment profiles

KaiMS defaults to the complete incident-management path without starting every
engineering tool. Lean mode retains ingestion, correlation, evidence collection,
RCA, model routing, orchestration, approval, remediation, closure, audit,
notification, periodic knowledge development, persistence, API, and UI.

| Profile | Services | Use |
|---|---:|---|
| `lean` (default) | 22 | Normal KaiMS operation and demonstrations |
| `observability` | 30 | Add Prometheus, Grafana, tracing, exporters, and Alertmanager |
| `monitoring-authoring` | 35 | Add rule generation, metric validation, Prometheus configuration, and dashboard generation |
| `evaluation` | 23 | Add offline/model evaluation service |
| `full` | 39 | Compatibility and engineering diagnostics |

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
rollback, audit, or continuous-learning controls. It excludes auxiliary
dashboards/exporters, monitoring-rule authoring workers, offline evaluation, and
Temporal's separate administration UI. Activate those profiles only for the
corresponding engineering task.
