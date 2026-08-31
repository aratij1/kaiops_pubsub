kind: runbook
title: RAG-DOC-2 document normalization runbook
services: unknown
owner_team: platform-ops
last_reviewed: 2026-07-08
source_system: internal
source_ref: RAG-DOC-2

# RAG-DOC-2 document normalization runbook

## Purpose
Provide a repeatable process to normalize ad-hoc uploaded documents into production-safe runbook markdown.

## Preconditions
- Write access to rag/runbooks
- Access to ingestion/indexing diagnostics
- A validated source document for reconstruction

## Triage Signals
- Missing headings required by runbook template
- Non-markdown binary payload embedded in file
- Search results for this runbook are empty or low quality

## Investigation Steps
1. Inspect file encoding and markdown structure.
2. Compare current file against runbook template requirements.
3. Identify impacted alerts that depend on this runbook.

## Troubleshooting Steps
1. Normalize frontmatter and section headers.
2. Fill mandatory response sections including troubleshooting and escalation.
3. Run backfill/validation scripts and verify parser compatibility.
4. Confirm retrieval quality from context-agent query samples.

## Remediation Steps
1. Replace malformed sections with clean markdown equivalents.
2. Keep operational steps concise, reversible, and testable.
3. Commit and publish update for deterministic retrieval behavior.

## Validation
- Required sections are present and ordered logically
- No binary payload markers in file content
- Runbook is discoverable by alert ID and title

## Rollback
1. Revert to prior known-good version from git.
2. Mark file as excluded from indexing until corrected.

## Escalation
- Escalate to platform-ops for repeated formatting regressions.
- Escalate to tooling owners for conversion pipeline hardening.

## Notes
- Prefer markdown-native authoring for runbook artifacts.
- Add CI linting for runbook structure and encoding checks.
