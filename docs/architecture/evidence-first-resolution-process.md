# Evidence-first resolution process

## Objective

Resolution must investigate the affected application before proposing a corrective operation. It consumes the immutable context snapshot collected by Context Intelligence and produces an auditable chain from evidence to hypothesis to governed execution plan.

## Process

```text
alert and application identity
  -> Context Intelligence crawls configured sources in parallel
       logs, metrics/traces, source code/config, deployments/changes,
       databases, tickets, reviewed runbooks, and prior incidents
  -> Resolution builds a crawl manifest
       collected sources, evidence IDs, freshness, and explicit gaps
  -> Durable iterative investigation
       select the highest-value missing read-only query
       persist the query, result, and hypothesis revision
       repeat within step/evidence budgets until conclusive or inconclusive
  -> Resolution ranks hypotheses
       current operational signals first
       code/change correlation second
       historical incidents as precedent, never as current fact
  -> RCA synthesis
       cite only admitted evidence IDs
       record alternatives and falsification checks
       cap confidence when source coverage is incomplete
  -> Impact analysis
       separate observed impact from unverified business risk
  -> Corrective-plan synthesis
       use code, logs, changes, prior outcomes, and approved runbooks
       require preflight, validation, rollback, idempotency, and target
  -> Governed catalog matching
       match with alert identity plus RCA, action, and ranked hypotheses
       bind only connector-allowed operations
  -> policy and approval
  -> execution
  -> independent recovery validation
  -> closure
```

## Output contracts

Each recommendation now carries:

- `iterative_investigation`: durable status, stop reason, query steps, revised hypotheses, coverage, gaps, and next-evidence guidance.
- `investigation_report`: per-source coverage, missing sources, crawl steps, and source evidence IDs.
- `hypothesis_analysis`: ranked causes, confidence, supporting evidence, prior outcomes, and falsification checks.
- `rca_analysis`: accepted citations, alternatives, missing evidence, and evidence-quality limits.
- `remediation_analysis`: proposed action, validation, rollback, readiness blocks, evidence basis, and ranked hypotheses.
- `execution_plan`: the reviewed catalog plan enriched with evidence basis, investigation report, and historical precedents.

## Safety and quality rules

1. Historical incidents and RAG documents are guidance, not proof of a current condition.
2. A model cannot cite evidence that was not admitted into the context package.
3. Missing application evidence lowers the confidence ceiling.
4. A mutating model proposal is not execution-ready without application evidence, sufficient causal corroboration, validation, and rollback.
5. The executable plan still comes from the reviewed action/playbook catalog and connector allow-list.
6. Catalog selection uses RCA and ranked hypotheses in addition to the raw alert, preventing generic alert text from dominating playbook choice.
7. Diagnostic-only completion remains distinct from validated recovery: it may close the analysis workflow but must not claim that health was restored or alerts cleared.
8. Only the allow-listed Discovery MCP reads (`logs.search`, `code.search`, `telemetry.search`, `tickets.search`, and `mysql.search`) may run during investigation.
9. An investigation requires corroboration across evidence planes before becoming conclusive. An inconclusive or budget-exhausted result cannot yield an executable plan; the catalog candidate is retained only for review.

## Operations

Deep RCA, impact, and remediation synthesis is enabled by default with `RESOLUTION_DEEP_ANALYSIS_ENABLED=true`. Set it to `false` only as an explicit degraded-mode latency/cost control; the deterministic evidence and safety gates remain active.

Iterative investigation is enabled with `RESOLUTION_ITERATIVE_INVESTIGATION_ENABLED=true`. Its bounded defaults are four tool steps, 40 evidence records, and a `0.78` conclusion threshold. Investigation, step, and hypothesis state is stored in `resolution_investigations`, `resolution_investigation_steps`, and `resolution_hypotheses`. The latest record is available through `GET /resolution/investigations/{incident_id}?tenant_id=...`.
