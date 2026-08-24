# KaiMS Phase 9 Architecture

## Operating model

KaiMS evolves incrementally around one governed lifecycle:

`Observe -> Understand -> Reason -> Plan -> Govern -> Act -> Verify -> Learn`

Existing incident, approval, remediation, validation, audit, and learning services remain authoritative. Phase 9 adds shared contracts beneath those services rather than constructing parallel stores or workflows.

## Canonical model layer

`common.operational_models` defines transport- and provider-neutral contracts for:

- operational resources with stable IDs independent of display names;
- application services and environments;
- typed resource relationships;
- connection, monitoring, ownership, SLO, change, knowledge, and remediation metadata;
- provenance containing source, observation time, last verification, confidence, and evidence.

Relationships are classified as discovered, declared, imported, or inferred. An inferred relationship without evidence is invalid. This rule prevents AI-produced topology from appearing as verified discovery.

These are domain contracts, not persistence claims. The Digital Twin milestone will add additive tables, repositories, discovery upserts, query APIs, and migrations.

## Event contract migration

New event boundaries use `CanonicalEventEnvelopeV1` and always serialize the full field set, including null entity identifiers where an event does not apply to an incident or resource. Tenant, trace, correlation, source, payload, and metadata are mandatory.

Existing nested `build_event_envelope` output remains supported. `canonical_event_from_legacy` maps its identity, scope, state, policy, transport, idempotency, and payload without mutating the original event. Producers migrate topic by topic; consumers must accept both formats during the compatibility window.

The canonical schema is published at `docs/metadata/canonical-event-envelope-v1.schema.json`.

## Safety invariants

1. Tenant identity is validated at contract construction.
2. Stable resource identity is not derived solely from display name.
3. AI inference is explicit and evidence-bearing.
4. Credentials remain references; these contracts never contain raw secret values.
5. Event replay cannot be used to authorize execution; execution continues to require capability, target, credential, policy, approval, idempotency, and validation controls.
6. Legacy payload adaptation preserves governance metadata for audit rather than silently discarding it.

## Compatibility and rollback

This milestone is additive: no database schema, endpoint, topic, or existing event builder changed. Rollback consists of removing the new modules, schema, tests, and this document. Existing services continue using their current contracts until explicitly migrated.

## Next increment

Build the persisted Operational Digital Twin foundation:

- additive resource and relationship migrations;
- tenant/project-scoped repositories with deterministic upsert identity;
- provenance and verification history;
- discovery adapters for existing onboarding/discovery outputs;
- read APIs for resource lookup, dependency traversal, and blast-radius queries;
- unit and integration tests for isolation, idempotency, inferred-edge labeling, and replay.

