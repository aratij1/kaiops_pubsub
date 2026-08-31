# Modernization Phase 20 — Accessibility and responsive UX

## Outcome

The shared workspace now has an explicit keyboard bypass path, consistent
high-visibility focus treatment, coarse-pointer touch targets, mobile reflow
guards, and safer document-dialog semantics and focus restoration.

## Delivered

- A first-focus “Skip to workspace content” link and programmatically focusable
  content landmark.
- A visible three-pixel focus indicator for native and custom interactive
  controls.
- Document prompt labelled as a modal dialog, initial focus on entry, Escape to
  close, and focus return to its invoking control.
- 44-pixel touch targets on coarse pointers and narrow-screen containment for
  panels, controls, and wide tables.
- Automated axe coverage plus keyboard bypass, 320-pixel reflow, and mobile
  navigation assertions.

## Acceptance boundary

Automated axe checks detect only a subset of WCAG failures. Production sign-off
still requires manual screen-reader passes (NVDA/JAWS and VoiceOver), 200%/400%
zoom review, contrast verification for tenant themes, and keyboard completion of
each privileged remediation workflow.
