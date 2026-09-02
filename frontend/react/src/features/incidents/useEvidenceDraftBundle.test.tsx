// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useEvidenceDraftBundle } from "./useEvidenceDraftBundle";

const draft = {
  draft_id: "10000000-0000-4000-8000-000000000001",
  document_kind: "jira", document_version: 2, row_version: 7,
  status: "reviewed" as const, title: "Jira draft", content: "reviewed content",
  evidence_ids: ["evidence-1"], source_uris: ["prometheus://query/test"],
};

describe("useEvidenceDraftBundle", () => {
  it("sends authenticated review and approval requests with row versions", async () => {
    const fetchJson = vi.fn().mockResolvedValue({ data: { draft } });
    const authenticatedOptions = vi.fn((options = {}) => ({
      ...options, authenticated: true, headers: { Authorization: "Bearer token" },
    }));
    const { result } = renderHook(() => useEvidenceDraftBundle({
      fetchJson, authenticatedOptions, unwrap: (value: any) => value.data,
    }));

    await result.current.review(draft, "updated reviewed content", "verified");
    await result.current.approve(draft);
    await result.current.revise(draft);

    const reviewOptions = fetchJson.mock.calls[0][1];
    const approveOptions = fetchJson.mock.calls[1][1];
    expect(JSON.parse(reviewOptions.body)).toMatchObject({ expected_row_version: 7, title: "Jira draft" });
    expect(JSON.parse(approveOptions.body)).toEqual({ expected_row_version: 7 });
    expect(reviewOptions.headers.Authorization).toBe("Bearer token");
    expect(approveOptions.headers.Authorization).toBe("Bearer token");
    expect(fetchJson).toHaveBeenNthCalledWith(
      3,
      "/api-gateway/rag/evidence-drafts/10000000-0000-4000-8000-000000000001/revision",
      expect.objectContaining({ method: "POST", authenticated: true }),
    );
  });

  it("loads the latest server versions after a conflict", async () => {
    const fetchJson = vi.fn().mockResolvedValue({ data: { drafts: [draft] } });
    const { result } = renderHook(() => useEvidenceDraftBundle({
      fetchJson, authenticatedOptions: (options = {}) => ({ ...options, authenticated: true }),
      unwrap: (value: any) => value.data,
    }));
    expect(await result.current.load("alert/id")).toEqual([draft]);
    expect(fetchJson).toHaveBeenCalledWith(
      "/api-gateway/rag/evidence-drafts?alert_id=alert%2Fid",
      expect.objectContaining({ authenticated: true }),
    );
  });
});
