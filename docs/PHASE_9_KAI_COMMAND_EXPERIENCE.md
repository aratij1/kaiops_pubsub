# Phase 9 — Kai Copilot and Command Experience

Milestone 18 adds a global keyboard-first command palette and connects free-text operational questions to the existing governed Kai Copilot.

## Implemented

- `Ctrl/Cmd + K` opens Kai Command from every authenticated workspace.
- Operators can find applications, incidents, services/resources, approvals, integrations, and settings.
- Results reuse the canonical navigation registry and its two-role authorization rules.
- Keyboard navigation supports arrows, Enter, Escape, focus placement, and dialog semantics.
- Unmatched free text becomes an explicit Ask Kai handoff with the question prefilled.
- The palette does not contain execute, approve, or remediation commands. Copilot remains read-only and authenticated, and its output remains subject to normal evidence and policy controls.
- Reduced-motion preferences are respected.

## Compatibility and rollback

No backend, schema, or event changes are required. Existing Copilot requests and navigation routes remain unchanged. Rollback removes the palette component and the optional `query` initialization in Copilot.

## Known limitations

- Entity commands open their authorized workspace; cross-entity server search remains bounded to the existing loaded-data search capability.
- Copilot's current deterministic backend supports capacity, assignment, and onboarding intents. Broader evidence-grounded incident questions require future read-only intent adapters.

## Recommended next milestone

Milestone 19: readiness and autonomy dashboards.
