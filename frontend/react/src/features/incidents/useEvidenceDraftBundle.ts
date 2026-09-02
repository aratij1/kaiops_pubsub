import { useCallback } from "react";

export interface EvidenceDraft {
  draft_id: string;
  document_kind?: string;
  document_version?: number;
  row_version: number;
  status?: "draft" | "reviewed" | "approved_pending_index" | "approved";
  title: string;
  content: string;
  evidence_ids?: string[];
  source_uris?: string[];
  reviewed_by?: string | null;
}

const conflictMessage = "This draft changed after you opened it. Review the latest version before saving.";

export function isEvidenceDraftConflict(error: unknown) {
  const value = String((error as { message?: string })?.message || error || "");
  return /409|stale_evidence_draft|changed by another reviewer/i.test(value);
}

export function useEvidenceDraftBundle({ fetchJson, authenticatedOptions, unwrap }: any) {
  const load = useCallback(async (alertId: string) => {
    const response = await fetchJson(
      `/api-gateway/rag/evidence-drafts?alert_id=${encodeURIComponent(alertId)}`,
      authenticatedOptions(),
    );
    return (unwrap(response)?.drafts || []) as EvidenceDraft[];
  }, [authenticatedOptions, fetchJson, unwrap]);

  const review = useCallback(async (draft: EvidenceDraft, content: string, notes: string) => {
    return fetchJson(
      `/api-gateway/rag/evidence-drafts/${encodeURIComponent(draft.draft_id)}`,
      authenticatedOptions({
        method: "PUT",
        body: JSON.stringify({
          expected_row_version: draft.row_version,
          title: draft.title,
          content,
          review_notes: notes,
        }),
      }),
    );
  }, [authenticatedOptions, fetchJson]);

  const approve = useCallback(async (draft: EvidenceDraft) => {
    return fetchJson(
      `/api-gateway/rag/evidence-drafts/${encodeURIComponent(draft.draft_id)}/approve`,
      authenticatedOptions({
        method: "POST",
        body: JSON.stringify({ expected_row_version: draft.row_version }),
      }),
    );
  }, [authenticatedOptions, fetchJson]);

  const revise = useCallback(async (draft: EvidenceDraft) => {
    return fetchJson(
      `/api-gateway/rag/evidence-drafts/${encodeURIComponent(draft.draft_id)}/revision`,
      authenticatedOptions({ method: "POST", body: JSON.stringify({}) }),
    );
  }, [authenticatedOptions, fetchJson]);

  return { load, review, approve, revise, conflictMessage };
}
