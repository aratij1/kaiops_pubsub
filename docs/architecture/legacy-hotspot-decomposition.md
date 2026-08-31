# Legacy hotspot decomposition

KaiMS uses a strangler approach: existing behavior remains available while cohesive
feature slices move behind typed, tested module boundaries. The CI architecture
budget prevents the four largest entry points from growing beyond their current
line counts. Any feature touching a hotspot must keep it flat or extract more than
it adds.

## Extraction order

1. Move pure identity, filtering, and presentation transforms out of `App.jsx` and
   `appHelpers.jsx`; cover each extraction with unit tests.
2. Move monitoring inventory, onboarding, and provider-specific handlers out of
   `monitoring-adapter/app.py` into its package.
3. Extend the API gateway's existing `modules/` structure to remediation, projects,
   health aggregation, and alert workflow concerns.
4. Enable JavaScript checking one extracted directory at a time, then retire the
   two ESLint exclusions after the legacy shell is thin enough.

Optional infrastructure clients should move from the root Python dependency set
only after service-specific dependency manifests exist. Removing them first would
make feature-flagged production entry points fail at import time.
