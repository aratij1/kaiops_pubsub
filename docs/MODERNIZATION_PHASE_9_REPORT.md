# KaiOps modernization: Phase 9 report

Date: 2026-08-04 (Asia/Calcutta)

## Scope completed

The RCA workspace now distinguishes direct observation, AI inference, cached context, fresh discovery, conflicting evidence, and missing evidence. Evidence rows expose source, timestamp, age, freshness, citation, and cache status. Recommendation context exposes confidence and its reasons, provider/model availability, fallback usage, and attempt-history availability. Operators can submit Helpful, Incorrect, or Incomplete feedback to the existing persisted evaluation service.

## Files reviewed

- evaluation-service feedback contract and MySQL repository
- API gateway proxy/audit conventions
- resolution evaluation and model-usage metadata
- discovery, RAG document, and workflow evidence contracts

## Files created

- `frontend/react/artifacts/phase9-ai-trust-evidence.png`
- `docs/MODERNIZATION_PHASE_9_REPORT.md`

## Files modified

- `backend/src/api-gateway/app.py`
- `frontend/react/src/App.jsx`
- `frontend/react/src/styles.css`
- `frontend/react/tests/e2e/discovery-layout.spec.js`

## Architecture decisions

1. Reuse the existing evaluation-service feedback persistence instead of adding client-only storage.
2. Proxy feedback through the authenticated, audited API gateway; the browser never calls an internal service directly.
3. Derive trust labels only from returned metadata and explicitly identify absent fields.
4. Treat MCP discovery results as fresh unless marked otherwise and linked knowledge documents as cached unless their contract says otherwise.
5. Display citations as text because internal `log://`, `ticket://`, and `code://` schemes are not safe browser destinations.

## Existing functionality preserved

- RCA generation/regeneration, document retrieval, downloads, approval, and remediation
- existing evaluation creation and approval-linked feedback
- authentication, API paths, workflow contracts, and MySQL persistence

## API contracts affected

Added an API-gateway proxy route:

```text
POST /evaluations/by-recommendation/{recommendation_id}/feedback
```

It forwards the existing `{decision, approver, comment}` contract and preserves the evaluation service's `{updated}` response.

## MySQL impact

No schema change. Feedback uses the existing MySQL-backed `EvaluationRepository`. No PostgreSQL or pgvector dependency was introduced.

## Security implications

- feedback is sent with the current access token through the gateway
- gateway safety analysis and audit capture apply to feedback requests
- untrusted internal evidence URIs are not made clickable
- missing provenance and model metadata are disclosed, not fabricated

## Feature flags added

None; an existing production feedback API was available.

## Tests added or updated

The browser journey verifies all six trust classifications, model/fallback disclosure, persisted Helpful feedback, and a focused screenshot. Axe reports no serious or critical violations.

## Commands executed and results

```text
python -m py_compile backend/src/api-gateway/app.py        PASS
npm run typecheck                                          PASS
npm run test:unit                                          PASS: 14/14
npm run build                                              PASS
npx playwright test discovery-layout accessibility        PASS: 2/2
npx playwright test discovery-layout                      PASS: 1/1 after capture refinement
```

## Build and performance measurements

- shared entry: 241.66 KB raw / 77.72 KB gzip
- legacy application: 651.22 KB raw / 158.19 KB gzip
- CSS: 131.41 KB raw / 24.33 KB gzip

The panel adds no polling. Feedback is a single operator-triggered request.

## Screenshot

`frontend/react/artifacts/phase9-ai-trust-evidence.png` was visually inspected. It clearly shows confidence, evidence classification, provenance, feedback, and honest missing-data states.

## Known limitations

- recommendation-attempt comparison is disclosed as unavailable when the backend does not return history
- document timestamps/freshness remain unknown where source contracts omit timestamps
- model/provider identity is unavailable for workflows that do not emit usage metadata
- the legacy application chunk remains above Vite's 500 KB warning threshold

## Rollback procedure

1. Remove the feedback proxy route.
2. Remove trust derivation, feedback state/action, panel styles, and browser assertions.
3. Remove the screenshot and this report.
4. Run backend compile, frontend type/unit/build, Playwright, and Axe checks.

The existing evaluation service and stored feedback remain compatible; no database rollback is required.

## Recommended next phase

Proceed directly to Phase 10 global operational capabilities: global entity search, My Work, collaboration/notification visibility, subscriptions, quiet hours, and export only where real backend contracts exist.
