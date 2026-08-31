# ADR-001: frontend component foundation

Status: accepted for Phase 3  
Date: 2026-08-04

## Decision

Use **React Aria Components** as the single accessible interaction foundation and **Lucide React** as the icon set. Keep vanilla CSS through central KaiOps design tokens. Use Storybook with the React/Vite framework and accessibility addon for isolated component documentation.

## Rationale

- React Aria is style-neutral, so it preserves the existing KaiOps light/dark visual identity rather than introducing a competing theme system.
- It supplies keyboard, focus, pressed, selected, overlay, and dialog behavior for interaction patterns that commonly fail accessibility review.
- Imports are component-level and compatible with the existing React 18/Vite application.
- MUI was not selected because its theme and styling would create a second visual system and a larger immediate migration surface.
- Radix primitives were not selected because equivalent initial components would require more composition code.
- Lucide is an icon set rather than another component system; it replaces ambiguous two-letter glyphs consistently.

## Consequences

- Existing legacy controls remain until migrated incrementally.
- New shared interactive components must use React Aria rather than mixing MUI, Radix, or another widget system.
- Shared styles consume `src/styles/tokens.css` and `src/components/design-system/design-system.css`.
- Storybook is development-only and is not included in the production application.

## Rollback

Remove the shared components, Storybook configuration, token stylesheet imports, React Aria/Lucide dependencies, and restore the five sidebar icon strings. No backend, API, authentication, or MySQL rollback is required.
