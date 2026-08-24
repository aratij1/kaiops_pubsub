# Phase 9 — Incident Workspace and Evidence Graph UX

The incident details view now begins with one decision-oriented workspace. It
shows severity, state, application, environment, duration, owner and autonomy
mode, followed by the visible Observe → Understand → Reason → Govern → Act →
Verify → Learn lifecycle.

Question cards expose persisted incident, change, diagnosis, impact, plan,
validation and learning fields. Missing values are rendered as unavailable.
The causal graph reads only persisted evidence/causal graph nodes and edges. It
does not infer a display graph from labels. Observed facts, verified topology,
correlation, AI inference, hypotheses and contradictions receive distinct text
labels and styles. Every node can be opened to inspect its source and detail.

Existing stage inspectors, source payloads, manual closure controls and deep
links remain available below the unified workspace. Rollback consists of
removing the workspace component; no route, API or stored record changed.
