import { queryClient } from "../app/queryClient";
import { parseInternalApiResponse } from "../schemas/apiContracts";

export type RouteRequestOptions = RequestInit & { maxAttempts?: number; timeoutMs?: number; staleTimeMs?: number };

async function requestNetwork<T>(path: string, options: RouteRequestOptions): Promise<T> {
  const attempts = Math.min(Math.max(Math.floor(options.maxAttempts ?? 3), 1), 4);
  const timeoutMs = options.timeoutMs ?? 15_000;
  const request: RouteRequestOptions = { ...options };
  delete request.maxAttempts;
  delete request.timeoutMs;
  delete request.staleTimeMs;
  let lastError: unknown;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const controller = new AbortController();
    const forwardAbort = () => controller.abort(options.signal?.reason);
    options.signal?.addEventListener("abort", forwardAbort, { once: true });
    const timeout = globalThis.setTimeout(() => controller.abort(new DOMException("Request timed out", "TimeoutError")), timeoutMs);
    try {
      const headers = new Headers(request.headers);
      if (!headers.has("Accept")) headers.set("Accept", "application/json");
      if (request.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
      const response = await fetch(path, { ...request, headers, signal: controller.signal });
      const text = await response.text();
      if (!response.ok) {
        const error = new Error(`HTTP ${response.status}: ${text || "request failed"}`);
        if (response.status < 500 || attempt === attempts) throw error;
        lastError = error;
      } else {
        const payload = text ? JSON.parse(text) : null;
        return parseInternalApiResponse(path, String(request.method || "GET"), payload) as T;
      }
    } catch (error) {
      lastError = error;
      if (options.signal?.aborted || attempt === attempts) throw error;
    } finally {
      globalThis.clearTimeout(timeout);
      options.signal?.removeEventListener("abort", forwardAbort);
    }
    await new Promise((resolve) => globalThis.setTimeout(resolve, attempt * 500));
  }
  throw lastError instanceof Error ? lastError : new Error("Request failed");
}

/** Temporary typed boundary for route-owned adapters during legacy-shell retirement. */
export async function routeJson<T = unknown>(path: string, options: RouteRequestOptions = {}): Promise<T> {
  const method = String(options.method || "GET").toUpperCase();
  if (method !== "GET") {
    const result = await requestNetwork<T>(path, options);
    await queryClient.invalidateQueries({ queryKey: ["route-api"] });
    return result;
  }
  const authenticated = new Headers(options.headers).has("Authorization");
  return queryClient.fetchQuery({
    queryKey: ["route-api", authenticated ? "authenticated" : "public", path],
    queryFn: ({ signal }) => requestNetwork<T>(path, { ...options, signal }),
    staleTime: options.staleTimeMs ?? 0,
  });
}
