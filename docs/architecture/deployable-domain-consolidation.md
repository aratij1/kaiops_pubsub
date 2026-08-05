# KaiOps deployable-domain decision record

Date: 2026-08-04

Python packages remain modular. Production ownership is grouped into five deployable domains:

| Domain | Modules/services | Independent boundary rationale |
|---|---|---|
| Platform API/BFF | API gateway, user/RBAC, application onboarding, dashboard/config APIs | Internet-facing security policy, synchronous availability, horizontal request scaling |
| Alert ingestion and correlation | monitoring adapter, ingestion worker, alert intelligence, discovery MCP | burst scaling, connector isolation, backpressure and untrusted-input boundary |
| Incident workflow workers | orchestrator, context, resolution, approval, closure, optional Temporal worker | durable workflow recovery and worker scaling; context/resolution retain module boundaries |
| Integration and remediation workers | rule/config/validation generators, notification, remediation | privileged credentials and stronger execution isolation |
| Evaluation and AI services | model router, evaluation service, RAG/discovery services | GPU/provider scaling, cost control, independent model release cadence |

The current Compose topology remains the compatibility deployment while consolidation proceeds at the deployment-manifest layer. Services are not combined into one Python process because mounted FastAPI lifespans, queue consumers, privileged remediation credentials, and independent scaling would otherwise be silently broken. All images already share the same Python runtime and package set; the next deployment-layer consolidation can schedule modules within the five domains without merging source packages or changing APIs.

## Exit checks before reducing a process boundary

- dependency graph and port/DNS aliases documented
- startup/shutdown lifespans and background consumers preserved
- scaling and resource requests measured
- security identities and secrets remain least-privileged
- failure injection proves one module cannot take down an unrelated domain
- rollback restores the compatibility Compose service
- existing API, event-contract, MySQL, and browser tests pass
