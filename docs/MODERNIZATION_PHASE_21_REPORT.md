# Modernization Phase 21 — Frontend performance budgets

## Outcome

Frontend dependency groups are emitted as long-lived cacheable chunks and the
build now has a fail-closed gzip budget. This turns bundle growth into a visible
CI/build failure rather than a late user-experience regression.

## Delivered

- Stable React/router, TanStack, icon, accessibility, and shared vendor chunks.
- Per-file gzip reporting with a 150 KiB JavaScript and 30 KiB CSS ceiling.
- `npm run build:budget` for release pipelines.
- Existing alert stream virtualization, staged initial loading, 60-second
  background polling, and SSE invalidation remain in place.

## Next structural optimization

The legacy application shell is still a large route-level module. Further
reduction requires extracting each workspace implementation—not only its route
wrapper—out of `App.jsx`. That is intentionally tracked as refactoring work and
must be measured against end-to-end workflow parity.
