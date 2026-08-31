# Kai Design System

The public design-system API lives in `frontend/react/src/design-system` and is
organized into tokens, components, patterns, icons, motion and themes. It
extends the existing accessible React Aria component foundation and Storybook
surface instead of creating a competing library.

Tokens cover brand and semantic colors, typography, spacing, radius, borders,
elevation, motion, breakpoints and z-index. Dark is the default signature theme;
light and automatic modes remain supported. Product components must consume
semantic tokens and communicate status without relying on color alone.
