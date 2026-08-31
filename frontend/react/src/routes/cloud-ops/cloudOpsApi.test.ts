import { afterEach, describe, expect, it, vi } from "vitest";

import { listResources } from "./cloudOpsApi";

describe("cloud operations API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("routes resource requests through the authenticated API gateway", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { rows: [], count: 0 } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(listResources("session-token", "demo-project")).resolves.toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api-gateway/cloud-ops/resources?project_id=demo-project",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer session-token",
        }),
      }),
    );
  });

  it("fails locally when the authenticated session is missing", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(listResources("", "demo-project")).rejects.toThrow("Not authenticated");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
