import { useEffect, useMemo, useState } from "react";
import { routeJson } from "../../services/routeApi";
import { useSession } from "../../app/SessionContext";
import { isEvidenceDraftConflict, useEvidenceDraftBundle } from "../../features/incidents/useEvidenceDraftBundle";
import "./EvidenceDraftReview.css";

interface EvidenceDraft { draft_id: string; context_snapshot_id?: string; recommendation_id?: string; document_kind?: string; document_version?: number; row_version: number; title: string; status?: "draft" | "reviewed" | "approved_pending_index" | "approved"; content: string; evidence_ids?: string[]; source_uris?: string[]; reviewed_by?: string; updated_at?: string; }
const DOCUMENT_KINDS = ["incident", "jira", "runbook", "deployment", "change", "dependency", "remediation"];

export default function EvidenceDraftReview({ alertId, contextSnapshotId, recommendationId }: { alertId?: string | null; contextSnapshotId?: string | null; recommendationId?: string | null }) {
  const { accessToken } = useSession();
  const [draft, setDraft] = useState<EvidenceDraft | null>(null);
  const [drafts, setDrafts] = useState<EvidenceDraft[]>([]);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const approved = draft?.status === "approved" || draft?.status === "approved_pending_index";
  const changed = Boolean(draft && content !== String(draft.content || ""));
  const words = useMemo(() => content.trim() ? content.trim().split(/\s+/).length : 0, [content]);
  const authenticatedOptions = (options: Record<string, unknown> = {}) => ({
    ...options,
    authenticated: true,
    headers: { Authorization: `Bearer ${accessToken}`, ...((options.headers as Record<string, string>) || {}) },
  });
  const unwrap = (response: any) => response?.data || response;
  const draftApi = useEvidenceDraftBundle({ fetchJson: routeJson, authenticatedOptions, unwrap });

  async function loadDraft() {
    if (!alertId || !accessToken) return;
    setLoading(true); setMessage(null);
    try {
      const response: any = await routeJson(`/api-gateway/rag/evidence-drafts?alert_id=${encodeURIComponent(alertId)}`, authenticatedOptions({ timeoutMs: 10000 }));
      const loaded: EvidenceDraft[] = (response?.data || response)?.drafts || [];
      const current = loaded.filter((item) => (!contextSnapshotId || item.context_snapshot_id === contextSnapshotId)
        && (!recommendationId || item.recommendation_id === recommendationId));
      const next = current.find((item) => item.document_kind === draft?.document_kind) || current[0] || null;
      setDrafts(current);
      setDraft(next); setContent(String(next?.content || ""));
    } catch (error: any) { setMessage({ tone: "error", text: error?.message || "Unable to load the evidence draft." }); }
    finally { setLoading(false); }
  }

  useEffect(() => { void loadDraft(); }, [accessToken, alertId, contextSnapshotId, recommendationId]);

  function selectDraft(next: EvidenceDraft) {
    if (changed && !window.confirm("Discard unsaved changes and open another document?")) return;
    setDraft(next); setContent(String(next.content || "")); setMessage(null);
  }

  async function save(approve: boolean) {
    if (!draft) return;
    if (content.trim().length < 40) { setMessage({ tone: "error", text: "Add a meaningful evidence summary before continuing." }); return; }
    setLoading(true); setMessage(null);
    try {
      const response: any = approve
        ? await draftApi.approve(draft)
        : await draftApi.review(draft, content, "");
      const next = (response?.data || response)?.draft || draft;
      setDraft(next); setContent(String(next.content || content));
      setDrafts((current) => current.map((item) => item.draft_id === next.draft_id ? next : item));
      setMessage({ tone: "success", text: approve ? "Approved — indexing pending." : "Review saved. The draft remains excluded from grounding." });
    } catch (error: any) {
      if (isEvidenceDraftConflict(error)) { await loadDraft(); setMessage({ tone: "error", text: draftApi.conflictMessage }); }
      else setMessage({ tone: "error", text: error?.message || "Unable to update the evidence draft." });
    }
    finally { setLoading(false); }
  }

  async function revise() {
    if (!draft) return;
    setLoading(true); setMessage(null);
    try {
      const response: any = await draftApi.revise(draft);
      const next = (response?.data || response)?.draft;
      if (!next) throw new Error("The replacement draft was not returned.");
      setDraft(next); setContent(String(next.content || ""));
      setDrafts((current) => [next, ...current.filter((item) => item.draft_id !== next.draft_id)]);
      setMessage({ tone: "success", text: `Version ${next.document_version} is editable. The published version remains available as evidence.` });
    } catch (error: any) { setMessage({ tone: "error", text: error?.message || "Unable to create an editable version." }); }
    finally { setLoading(false); }
  }

  if (!alertId) return null;
  return <details className="evidence-draft-workbench">
    <summary><span><strong>Governed documents</strong><small>{drafts.length ? `${drafts.length} incident documents available for review` : "Runbooks and incident records"}</small></span><b>Open document workspace</b></summary>
    <div className="evidence-draft-workbench-content">
    <header><div><span className="discovery-eyebrow">Evidence knowledge</span><h3>Review the generated draft</h3><p>Correct the AI-generated record, then publish it only when the evidence is accurate. Your signed-in identity is recorded automatically.</p></div><button type="button" className="button-secondary" onClick={loadDraft} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button></header>
    {draft ? <>
      <nav className="evidence-document-tabs" aria-label="Incident document drafts">{DOCUMENT_KINDS.map((kind) => { const item = drafts.find((candidate) => (candidate.document_kind || "incident") === kind); return <button key={kind} type="button" className={item?.draft_id === draft.draft_id ? "is-active" : ""} disabled={!item} onClick={() => item && selectDraft(item)}>{kind === "jira" ? "Jira Ticket" : kind[0].toUpperCase() + kind.slice(1)}</button>; })}</nav>
      <div className="evidence-document-title"><span className="discovery-eyebrow">{draft.document_kind || "incident"} · version {draft.document_version || 1}</span><strong>{draft.title || "Incident document"}</strong><small>{draft.status === "approved_pending_index" ? "Approved — indexing pending." : `${draft.status || "draft"} · reviewer ${draft.reviewed_by || "not assigned"}`}</small></div>
      <ol className="evidence-review-steps" aria-label="Evidence review progress"><li className="is-complete"><b>1</b><span><strong>AI generated</strong><small>{draft.evidence_ids?.length || 0} linked source records</small></span></li><li className={draft.status === "reviewed" || approved ? "is-complete" : "is-current"}><b>2</b><span><strong>Human review</strong><small>{changed ? "Unsaved edits" : draft.reviewed_by ? `Reviewed by ${draft.reviewed_by}` : "Awaiting review"}</small></span></li><li className={approved ? "is-complete" : ""}><b>3</b><span><strong>Publish evidence</strong><small>{approved ? "Available to investigations" : "Grounding blocked"}</small></span></li></ol>
      <div className="evidence-editor-layout"><section><div className="evidence-editor-heading"><label htmlFor="evidence-draft-content">Generated evidence document</label><span>{words} words</span></div><textarea id="evidence-draft-content" rows={12} value={content} onChange={(event) => setContent(event.target.value)} disabled={approved} aria-describedby="evidence-editor-help"/><small id="evidence-editor-help">AI-generated content is derived evidence. Correct unsupported claims before publishing; your authenticated identity is recorded automatically.</small></section><aside><dl><div><dt>Provenance</dt><dd>AI generated</dd></div><div><dt>Status</dt><dd>{approved ? "Published evidence" : draft.status === "reviewed" ? "Human reviewed" : "Editable draft"}</dd></div><div><dt>RCA grounding</dt><dd>{approved ? "Enabled" : "Blocked"}</dd></div><div><dt>Linked sources</dt><dd>{draft.evidence_ids?.length || 0}</dd></div></dl></aside></div>
      <footer><p>{approved ? "This published version remains immutable evidence. Editing creates a traceable replacement version." : "Save your corrections for review, then publish the exact reviewed version as governed evidence."}</p><div>{approved ? <button type="button" className="button-primary" onClick={() => void revise()} disabled={loading}>Edit as new version</button> : <><button type="button" className="button-secondary" onClick={() => void save(false)} disabled={loading || !changed}>Save review</button><button type="button" className="button-primary" onClick={() => void save(true)} disabled={loading || draft.status !== "reviewed" || !draft.evidence_ids?.length || !draft.source_uris?.length}>Publish as evidence</button></>}</div></footer>
    </> : !loading ? <div className="evidence-draft-empty"><strong>No document for this investigation version</strong><p>Historical drafts are excluded because they were generated from a different immutable evidence snapshot. Run the current analysis to generate a correctly bound document.</p><button type="button" className="button-secondary" onClick={loadDraft}>Check again</button></div> : null}
    {message ? <p className={message.tone} role="status">{message.text}</p> : null}
    </div>
  </details>;
}
