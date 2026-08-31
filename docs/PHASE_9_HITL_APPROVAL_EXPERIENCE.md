# Phase 9 — HITL approval experience

The approval workspace now opens with “Kai needs your decision” and presents a
decision packet rather than raw workflow payloads. It includes the incident,
diagnosis, confidence, evidence, resource, governed capability, exact target,
expected effect, risk, blast radius, preconditions, validation, rollback and an
execution preview. Raw plan and policy JSON remain available only in expandable
technical details.

Approve and Reject retain their existing signed readiness and immutable-plan
flows. Modify does not edit commands or an approved checksum: it submits a
structured request for Kai to compile a replacement typed plan, which must
receive a new checksum and be reviewed again. This intentionally fails closed.

No API or stored record was renamed. Rollback is limited to restoring the prior
route presentation; decision endpoints and receipts are unchanged.
