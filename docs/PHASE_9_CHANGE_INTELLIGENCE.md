# Phase 9 Change Intelligence

Milestone 10 introduces `kaims.change-event.v1` for Git commits, pull-request
merges, deployments, Jenkins, ArgoCD, Terraform, configuration changes, feature
flags, database changes, and ServiceNow changes.

Change correlation is deterministic and tenant-isolated. The score combines:

- incident-window proximity: 35%
- exact stable resource identity: 25%
- service identity: 15%
- environment identity: 10%
- verified topology-path identity: 15%

Temporal proximity alone is capped at 0.35. Every result explicitly carries
`causal_proof: false`; correlation can support a falsifiable hypothesis but
cannot independently confirm root cause. The Resolution Agent requires its
normal independent-source and confidence gates before selecting a primary RCA.

Investigation reports expose ranked correlations, component scores, reason
codes, evidence IDs, and the highest `change_correlation_score`. Evidence Graph
nodes retain source provenance and checksums.

## Backward compatibility

Existing `recent_changes` inputs remain supported. Canonical change events and
correlation results are additive investigation output. Invalid timestamps,
missing identities, and cross-tenant changes are excluded or rejected rather
than guessed.

## Remaining work

- Connector Hub plugins still need live collectors for all configured Git,
  ArgoCD, feature-flag, database-change, and ServiceNow environments.
- Durable normalized change-event persistence and query APIs will be added with
  the onboarding/control-plane storage work.
- Incident Workspace visualization is scheduled for milestone 15.
