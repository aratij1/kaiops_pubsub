import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "../../appHelpers.jsx";
import { useRouteRuntimeSlice } from "../../app/routeRuntime";
import { isEvidenceDraftConflict, useEvidenceDraftBundle } from "../../features/incidents/useEvidenceDraftBundle";
import "./EvidenceDraftReview.css";

interface EvidenceDraft { draft_id: string; document_kind?: string; document_version?: number; row_version: number; title: string; status?: "draft" | "reviewed" | "approved_pending_index" | "approved"; content: string; evidence_ids?: string[]; source_uris?: string[]; reviewed_by?: string; updated_at?: string; }
const DOCUMENT_KINDS = ["incident", "jira", "runbook", "deployment", "change", "dependency", "remediation"];

export default function EvidenceDraftReview({ alertId }: { alertId?: string | null }) {
  const { accessToken } = useRouteRuntimeSlice("session");
  const [draft, setDraft] = useState<EvidenceDraft | null>(null);
  const [drafts, setDrafts] = useState<EvidenceDraft[]>([]);
  const [content, setContent] = useState("");
  const [reviewer, setReviewer] = useState("");
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
  const draftApi = useEvidenceDraftBundle({ fetchJson, authenticatedOptions, unwrap });

  async function loadDraft() {
    if (!alertId || !accessToken) return;
    setLoading(true); setMessage(null);
    try {
      const response: any = await fetchJson(`/api-gateway/rag/evidence-drafts?alert_id=${encodeURIComponent(alertId)}`, authenticatedOptions({ timeoutMs: 10000 }));
      const loaded: EvidenceDraft[] = (response?.data || response)?.drafts || [];
      const next = loaded.find((item) => item.document_kind === draft?.document_kind) || loaded[0] || null;
      setDrafts(loaded);
      setDraft(next); setContent(String(next?.content || ""));
    } catch (error: any) { setMessage({ tone: "error", text: error?.message || "Unable to load the evidence draft." }); }
    finally { setLoading(false); }
  }

  useEffect(() => { void loadDraft(); }, [accessToken, alertId]);

  function selectDraft(next: EvidenceDraft) {
    if (changed && !window.confirm("Discard unsaved changes and open another document?")) return;
    setDraft(next); setContent(String(next.content || "")); setMessage(null);
  }

  async function save(approve: boolean) {
    if (!draft || !reviewer.trim()) { setMessage({ tone: "error", text: "Identify the reviewer before saving or approving." }); return; }
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

  if (!alertId) return null;
  return <article className="evidence-draft-workbench">
    <header><div><span className="discovery-eyebrow">Evidence knowledge</span><h3>Review the generated draft</h3><p>Correct the AI-generated record, identify yourself, then publish it only when the evidence is accurate.</p></div><button type="button" className="button-secondary" onClick={loadDraft} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button></header>
    {draft ? <>
      <nav className="evidence-document-tabs" aria-label="Incident document drafts">{DOCUMENT_KINDS.map((kind) => { const item = drafts.find((candidate) => (candidate.document_kind || "incident") === kind); return <button key={kind} type="button" className={item?.draft_id === draft.draft_id ? "is-active" : ""} disabled={!item} onClick={() => item && selectDraft(item)}>{kind === "jira" ? "Jira Ticket" : kind[0].toUpperCase() + kind.slice(1)}</button>; })}</nav>
      <div className="evidence-document-title"><span className="discovery-eyebrow">{draft.document_kind || "incident"} · version {draft.document_version || 1}</span><strong>{draft.title || "Incident document"}</strong><small>{draft.status === "approved_pending_index" ? "Approved — indexing pending." : `${draft.status || "draft"} · reviewer ${draft.reviewed_by || "not assigned"}`}</small></div>
      <ol className="evidence-review-steps" aria-label="Evidence review progress"><li className="is-complete"><b>1</b><span><strong>Generated</strong><small>{draft.evidence_ids?.length || 0} linked records</small></span></li><li className={reviewer.trim() ? "is-complete" : "is-current"}><b>2</b><span><strong>Human review</strong><small>{changed ? "Unsaved edits" : "Ready for review"}</small></span></li><li className={approved ? "is-complete" : ""}><b>3</b><span><strong>Publish</strong><small>{approved ? "Available to RCA" : "Grounding blocked"}</small></span></li></ol>
      <div className="evidence-editor-layout"><section><div className="evidence-editor-heading"><label htmlFor="evidence-draft-content">Verified incident knowledge</label><span>{words} words</span></div><textarea id="evidence-draft-content" rows={12} value={content} onChange={(event) => setContent(event.target.value)} disabled={approved} aria-describedby="evidence-editor-help"/><small id="evidence-editor-help">Keep observed facts, timestamps, affected services, cause, and confirmed resolution. Remove unsupported assumptions.</small></section><aside><label htmlFor="evidence-reviewer">Reviewer identity</label><input id="evidence-reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Name or operator ID" disabled={approved}/><dl><div><dt>Status</dt><dd>{approved ? "Published" : "Draft"}</dd></div><div><dt>RCA grounding</dt><dd>{approved ? "Enabled" : "Blocked"}</dd></div><div><dt>Linked evidence</dt><dd>{draft.evidence_ids?.length || 0}</dd></div></dl></aside></div>
      <footer><p>{approved ? "This version is read-only. Create a replacement draft to make further corrections." : "Review saves this exact version. Approval keeps it unavailable until indexing succeeds."}</p><div><button type="button" className="button-secondary" onClick={() => void save(false)} disabled={loading || approved || !changed}>Save review</button><button type="button" className="button-primary" onClick={() => void save(true)} disabled={loading || draft.status !== "reviewed" || !draft.evidence_ids?.length || !draft.source_uris?.length}>Approve reviewed version</button></div></footer>
    </> : !loading ? <div className="evidence-draft-empty"><strong>No draft has been generated yet</strong><p>Complete evidence collection and RCA generation, then refresh this panel.</p><button type="button" className="button-secondary" onClick={loadDraft}>Check again</button></div> : null}
    {message ? <p className={message.tone} role="status">{message.text}</p> : null}
  </article>;
}
