# RCA document verification lifecycle

KaiMS permits an evidence-backed RCA hypothesis to be created as a review draft while additional verification is pending. This resolves the prior deadlock where an operator could not review or enrich a document until the RCA was already fully verified.

Safety behavior remains fail-closed:

- A draft requires both a root-cause hypothesis and linked evidence.
- Review-required content is visibly labelled as an unverified hypothesis.
- Drafts remain outside the reusable RAG index.
- Operators may edit, add evidence, and save the draft.
- Approval and publication remain disabled until the RCA confidence, grounding, conclusive-investigation, conflict, and evidence-gap checks pass.
- Backend review and explicit approval remain required before a document enters reusable knowledge.

No database, API, or event-contract migration is required.
