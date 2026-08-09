import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "../../appHelpers.jsx";
import "./EvidenceDraftReview.css";

interface EvidenceDraft { draft_id: string; status?: string; content?: string; evidence_ids?: string[]; reviewed_by?: string; updated_at?: string; }

export default function EvidenceDraftReview({ alertId }: { alertId?: string | null }) {
  const [draft, setDraft] = useState<EvidenceDraft | null>(null);
  const [content, setContent] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const approved = draft?.status === "approved";
  const changed = Boolean(draft && content !== String(draft.content || ""));
  const words = useMemo(() => content.trim() ? content.trim().split(/\s+/).length : 0, [content]);

  async function loadDraft() {
    if (!alertId) return;
    setLoading(true); setMessage(null);
    try {
      const response: any = await fetchJson(`/api-gateway/rag/evidence-drafts?alert_id=${encodeURIComponent(alertId)}`, { timeoutMs: 10000 });
      const next = (response?.data || response)?.drafts?.[0] || null;
      setDraft(next); setContent(String(next?.content || ""));
    } catch (error: any) { setMessage({ tone: "error", text: error?.message || "Unable to load the evidence draft." }); }
    finally { setLoading(false); }
  }

  useEffect(() => { void loadDraft(); }, [alertId]);

  async function save(approve: boolean) {
    if (!draft || !reviewer.trim()) { setMessage({ tone: "error", text: "Identify the reviewer before saving or approving." }); return; }
    if (content.trim().length < 40) { setMessage({ tone: "error", text: "Add a meaningful evidence summary before continuing." }); return; }
    setLoading(true); setMessage(null);
    try {
      const response: any = await fetchJson(`/api-gateway/rag/evidence-drafts/${encodeURIComponent(draft.draft_id)}${approve ? "/approve" : ""}`, {
        method: approve ? "POST" : "PUT",
        body: JSON.stringify(approve ? { approved_by: reviewer.trim(), content } : { reviewed_by: reviewer.trim(), content }),
      });
      const next = (response?.data || response)?.draft || draft;
      setDraft(next); setContent(String(next.content || content));
      setMessage({ tone: "success", text: approve ? "Approved and published for future RCA grounding." : "Review saved. The draft remains excluded from grounding." });
    } catch (error: any) { setMessage({ tone: "error", text: error?.message || "Unable to update the evidence draft." }); }
    finally { setLoading(false); }
  }

  if (!alertId) return null;
  return <article className="evidence-draft-workbench">
    <header><div><span className="discovery-eyebrow">Evidence knowledge</span><h3>Review the generated draft</h3><p>Correct the AI-generated record, identify yourself, then publish it only when the evidence is accurate.</p></div><button type="button" className="button-secondary" onClick={loadDraft} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button></header>
    {draft ? <>
      <ol className="evidence-review-steps" aria-label="Evidence review progress"><li className="is-complete"><b>1</b><span><strong>Generated</strong><small>{draft.evidence_ids?.length || 0} linked records</small></span></li><li className={reviewer.trim() ? "is-complete" : "is-current"}><b>2</b><span><strong>Human review</strong><small>{changed ? "Unsaved edits" : "Ready for review"}</small></span></li><li className={approved ? "is-complete" : ""}><b>3</b><span><strong>Publish</strong><small>{approved ? "Available to RCA" : "Grounding blocked"}</small></span></li></ol>
      <div className="evidence-editor-layout"><section><div className="evidence-editor-heading"><label htmlFor="evidence-draft-content">Verified incident knowledge</label><span>{words} words</span></div><textarea id="evidence-draft-content" rows={12} value={content} onChange={(event) => setContent(event.target.value)} disabled={approved} aria-describedby="evidence-editor-help"/><small id="evidence-editor-help">Keep observed facts, timestamps, affected services, cause, and confirmed resolution. Remove unsupported assumptions.</small></section><aside><label htmlFor="evidence-reviewer">Reviewer identity</label><input id="evidence-reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Name or operator ID" disabled={approved}/><dl><div><dt>Status</dt><dd>{approved ? "Published" : "Draft"}</dd></div><div><dt>RCA grounding</dt><dd>{approved ? "Enabled" : "Blocked"}</dd></div><div><dt>Linked evidence</dt><dd>{draft.evidence_ids?.length || 0}</dd></div></dl></aside></div>
      <footer><p>{approved ? "This version is read-only. Create a replacement draft to make further corrections." : "Saving preserves work without exposing it to AI grounding. Approval publishes this exact version."}</p><div><button type="button" className="button-secondary" onClick={() => void save(false)} disabled={loading || approved || !changed}>Save draft</button><button type="button" className="button-primary" onClick={() => void save(true)} disabled={loading || approved || !reviewer.trim() || content.trim().length < 40}>Review and publish</button></div></footer>
    </> : !loading ? <div className="evidence-draft-empty"><strong>No draft has been generated yet</strong><p>Complete evidence collection and RCA generation, then refresh this panel.</p><button type="button" className="button-secondary" onClick={loadDraft}>Check again</button></div> : null}
    {message ? <p className={message.tone} role="status">{message.text}</p> : null}
  </article>;
}
