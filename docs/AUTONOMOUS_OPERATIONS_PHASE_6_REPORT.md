# Autonomous Operations Phase 6 — Bounded Differentiators

Date: 2026-08-21 (Asia/Calcutta)

## Outcome

Phase 6 adds typed safety boundaries for source-code RCA proposals, temporal service topology,
multi-judge evidence review, and preventive recommendations. These capabilities produce review
artifacts only; none can execute a patch or preventive operation.

## Delivered

- Versioned review-only code-patch proposals bound to repository, base revision, source URI, exact
  code evidence, unified diff, test plan, and declared limitations.
- Versioned temporal service-graph nodes and evidence-backed edges with validity intervals and
  point-in-time snapshots.
- Versioned evidence-council votes and decisions across independent causal, operations, safety, and
  domain roles.
- Deterministic council aggregation requiring at least three unique judge identities and roles,
  unanimous support, and multiple evidence records.
- Versioned preventive recommendations restricted to shadow/recommendation mode.

## Safety properties

- Patch proposals are structurally `review_required: true` and `executable: false`.
- A patch requires source-code evidence, a recognizable unified diff, and a test plan.
- Temporal graph edges cannot reference unknown nodes, use invalid intervals, or omit evidence.
- A single conflicting council vote yields `CONFLICTING_EVIDENCE` and operator review.
- Council support never removes the human-review requirement.
- Preventive recommendations require at least two evidence records, cannot contain commands, and
  always set `execution_authorized: false`.

## Verification

- Focused differentiator, graph, evidence, judge, and RCA evaluation tests: 42 passed.
- Changed Python modules: compilation passed.
- Focused diff whitespace validation: passed.

## Recommended next increment

Integrate these contracts into persisted API/event projections and the cockpit, add repository and
pull-request provider adapters behind explicit review gates, and ingest live topology changes into
the temporal graph. Keep all patch application and preventive operations disabled until their own
approval, sandbox, validation, rollback, and audit certification is complete.
