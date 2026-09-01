# Incident workspace responsive containment

The evidence workspace previously combined two sticky controls and intrinsic-width stage columns. In a sidebar-constrained desktop viewport this could create horizontal page scrolling, clip the left side of the RCA heading, and place the lifecycle rail over the analysis controls.

The corrected layout:

- keeps only the primary incident stage rail sticky on wide screens;
- leaves the inner RCA view and refresh toolbar in document flow;
- uses `minmax(0, 1fr)` and zero-minimum descendants to prevent intrinsic content from widening the page;
- switches the stage rail to two columns and stacks the evidence summary at sidebar-constrained widths;
- collapses analysis modes vertically on small screens.

This is presentation-only and does not change evidence, confidence, RCA, or approval state.
