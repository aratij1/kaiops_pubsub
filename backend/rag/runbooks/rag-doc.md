kind: runbook
title: RAG-DOC attachment ingestion runbook
services: unknown
owner_team: platform-ops
last_reviewed: 2026-07-08
source_system: internal
source_ref: RAG-DOC

# RAG-DOC attachment ingestion runbook

## Purpose
Restore normal runbook ingestion when uploaded document content is malformed or stored with binary payload artifacts.

## Preconditions
- Access to the RAG corpus repository
- Access to UI upload logs and context-agent ingestion logs
- Approval to replace malformed document with sanitized markdown

## Triage Signals
- File contains binary markers such as PK zip headers inside markdown
- Context retrieval quality degrades or returns unreadable snippets
- Ingestion or indexing logs show parse anomalies for this runbook

## Investigation Steps
1. Confirm document corruption by checking for binary signatures and malformed frontmatter.
2. Review recent upload events and identify the source upload action.
3. Validate whether related incident, deployment, and SOP docs remain healthy.

## Troubleshooting Steps
1. Extract useful textual content from the uploaded source if recoverable.
2. Rebuild a clean markdown document with standard runbook headers.
3. Re-index RAG corpus and verify this runbook appears in retrieval results.
4. Confirm no duplicate corrupted variants remain in the runbooks directory.

## Remediation Steps
1. Replace corrupted file with sanitized markdown content.
2. Preserve key metadata fields and ownership attributes.
3. Trigger RAG reload and validate search relevance for affected alert IDs.

## Validation
- Markdown file is UTF-8 text with no binary payload bytes
- RAG reload succeeds without parse warnings
- Retrieval returns coherent sections from this runbook

## Rollback
1. Restore previous file from git history if new content is incorrect.
2. Disable use of this runbook in decisioning until corrected.

## Escalation
- Escalate to platform-ops if parser errors persist after sanitization.
- Escalate to product owner if source upload pipeline repeatedly corrupts files.

## Notes
- Keep uploaded office documents outside markdown corpus unless converted first.
- Add validation hook to reject binary-like markdown payloads.
