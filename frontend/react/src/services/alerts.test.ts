import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AlertRowsResponseSchema } from "../schemas/alerts";
import { ApiValidationError, getValidated } from "./apiClient";
import { alertRowsQueryOptions } from "./alerts";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("typed alert API boundary", () => {
  it("normalizes nullable landing-pad fields in the gateway envelope", () => {
    const rows = AlertRowsResponseSchema.parse({
      trace_id: "trace-1",
      gateway: { path: "/landing-pad/recent" },
      data: { source: "live-memory-buffer", count: 1, rows: [
        { file: "alert.json", name: "HighLatency", application: null, metadata: null, status: "processed" },
      ] },
    });
    expect(rows).toEqual([expect.objectContaining({ name: "HighLatency", application: undefined, metadata: undefined })]);
  });

  it("accepts both gateway-wrapped and direct row responses", () => {
    expect(AlertRowsResponseSchema.parse({ data: { rows: [{ alert_id: "a-1", name: "CPU high" }] } })).toHaveLength(1);
    expect(AlertRowsResponseSchema.parse({ rows: [{ id: "a-2", service: "checkout" }] })).toHaveLength(1);
  });

  it("rejects malformed rows and logs only correlation-safe metadata", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { rows: "not-an-array" } }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    await expect(getValidated("/api-gateway/alerts/all?limit=10", AlertRowsResponseSchema)).rejects.toBeInstanceOf(ApiValidationError);
    expect(consoleError).toHaveBeenCalledWith("[kaiops-api-validation]", {
      endpoint: "/api-gateway/alerts/all",
      issueCount: expect.any(Number),
    });
    expect(JSON.stringify(consoleError.mock.calls)).not.toContain("not-an-array");
  });

  it("deduplicates concurrent requests with the same query key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { rows: [{ alert_id: "a-1" }] } }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const options = alertRowsQueryOptions(100);

    const [first, second] = await Promise.all([client.fetchQuery(options), client.fetchQuery(options)]);

    expect(first).toEqual(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("propagates query cancellation to the HTTP request", async () => {
    let observedSignal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn((_url: string | URL | Request, init?: RequestInit) => {
      observedSignal = init?.signal ?? undefined;
      return new Promise<Response>((_resolve, reject) => {
        observedSignal?.addEventListener("abort", () => reject(observedSignal?.reason), { once: true });
      });
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const pending = client.fetchQuery(alertRowsQueryOptions(100));

    await client.cancelQueries({ queryKey: alertRowsQueryOptions(100).queryKey, exact: true });

    await expect(pending).rejects.toBeDefined();
    expect(observedSignal?.aborted).toBe(true);
  });
});
