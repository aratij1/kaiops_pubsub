# Phase 9 Incident Evidence Graph and Causal RCA

Milestone 9 adds `kaims.incident-evidence-graph.v1` to every completed iterative
investigation. The graph contains immutable, checksummed nodes for alerts,
metrics, logs, traces, topology, changes, deployments, configuration, tickets,
similar incidents, runbooks, database observations, infrastructure health,
resources, and hypotheses.

Edges distinguish supporting evidence, contradicting evidence, temporal or
topological relationships, impact, and candidate causality. Relationship basis
is explicit: observed fact, verified topology, strong correlation, or AI
inference. A causal or AI-inferred edge cannot exist without cited evidence,
and causal inference is never represented as an observed fact.

Each hypothesis now exposes confidence, supporting and contradicting evidence,
affected resources, a causal path, and the next falsifying diagnostic. The graph
contains a primary hypothesis only when the RCA contract is conclusively
evidence-supported with independent corroboration. Low-confidence, conflicting,
or incomplete investigations expose alternatives and data gaps without
asserting unsupported root cause.

## Backward compatibility

Existing iterative-investigation, typed-hypothesis, and RCA result fields remain
unchanged. `evidence_graph` is additive. Removing the field restores the prior
consumer shape without changing persistence or event schemas.

## Remaining work

- Persist graph nodes and edges as independently queryable records rather than
  only inside investigation payloads.
- Add change-source correlation nodes and scoring in milestone 10.
- Build the Incident Workspace graph visualization in milestone 15.
