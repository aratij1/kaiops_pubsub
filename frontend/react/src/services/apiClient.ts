import type { ZodType, ZodTypeDef } from "zod";

export class ApiValidationError extends Error {
  readonly endpoint: string;
  readonly issueCount: number;

  constructor(endpoint: string, issueCount: number, message?: string) {
    super(message ?? `The ${endpoint} response did not match the expected contract.`);
    this.name = "ApiValidationError";
    this.endpoint = endpoint;
    this.issueCount = issueCount;
  }
}

export interface ValidatedRequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  method?: string;
  headers?: HeadersInit;
  body?: BodyInit | null;
}

export async function requestValidated<T>(
  endpoint: string,
  schema: ZodType<T, ZodTypeDef, unknown>,
  options: ValidatedRequestOptions = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(new DOMException("Request timed out", "TimeoutError")), options.timeoutMs ?? 7_000);
  const abortFromCaller = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) abortFromCaller();
  else options.signal?.addEventListener("abort", abortFromCaller, { once: true });

  try {
    const requestHeaders = new Headers(options.headers);
    if (!requestHeaders.has("Accept")) requestHeaders.set("Accept", "application/json");
    const response = await fetch(endpoint, {
      method: options.method ?? "GET",
      headers: requestHeaders,
      body: options.body,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`Request failed (${response.status}) for ${endpoint.split("?", 1)[0]}`);
    }
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.toLowerCase().includes("application/json")) {
      throw new Error(`Expected JSON from ${endpoint.split("?", 1)[0]}`);
    }
    const payload: unknown = await response.json();
    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      const error = new ApiValidationError(endpoint.split("?", 1)[0], parsed.error.issues.length);
      console.error("[kaiops-api-validation]", { endpoint: error.endpoint, issueCount: error.issueCount });
      throw error;
    }
    return parsed.data;
  } finally {
    globalThis.clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abortFromCaller);
  }
}

export function getValidated<T>(endpoint: string, schema: ZodType<T, ZodTypeDef, unknown>, options: ValidatedRequestOptions = {}): Promise<T> {
  return requestValidated(endpoint, schema, { ...options, method: "GET" });
}
