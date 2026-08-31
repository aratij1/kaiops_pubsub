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

export class ApiRequestError extends Error {
  readonly endpoint: string;
  readonly status: number;
  readonly code: string;
  readonly traceId?: string;
  readonly retryable: boolean;
  readonly retryAfterMs?: number;
  readonly category: string;

  constructor(options: {
    endpoint: string;
    status: number;
    code: string;
    message: string;
    traceId?: string;
    retryable?: boolean;
    category?: string;
    retryAfterMs?: number;
  }) {
    super(options.message);
    this.name = "ApiRequestError";
    this.endpoint = options.endpoint;
    this.status = options.status;
    this.code = options.code;
    this.traceId = options.traceId;
    this.retryable = options.retryable ?? false;
    this.category = options.category ?? "request";
    this.retryAfterMs = options.retryAfterMs;
  }
}

type ErrorEnvelope = {
  detail?: unknown;
  trace_id?: unknown;
  error?: {
    code?: unknown;
    message?: unknown;
    retryable?: unknown;
    category?: unknown;
    trace_id?: unknown;
  };
};

async function errorFromResponse(response: Response, endpoint: string): Promise<ApiRequestError> {
  let payload: ErrorEnvelope = {};
  if ((response.headers.get("content-type") || "").toLowerCase().includes("application/json")) {
    try {
      payload = await response.json() as ErrorEnvelope;
    } catch {
      payload = {};
    }
  }
  const contract = payload.error && typeof payload.error === "object" ? payload.error : {};
  const detail = typeof payload.detail === "string" ? payload.detail : undefined;
  const message = typeof contract.message === "string"
    ? contract.message
    : detail || `Request failed (${response.status}).`;
  const retryAfterSeconds = Number(response.headers.get("retry-after"));
  return new ApiRequestError({
    endpoint,
    status: response.status,
    code: typeof contract.code === "string" ? contract.code : `http_${response.status}`,
    message,
    traceId: String(contract.trace_id || payload.trace_id || response.headers.get("x-trace-id") || "") || undefined,
    retryable: typeof contract.retryable === "boolean"
      ? contract.retryable
      : [408, 425, 429, 502, 503, 504].includes(response.status),
    category: typeof contract.category === "string" ? contract.category : "request",
    retryAfterMs: Number.isFinite(retryAfterSeconds) && retryAfterSeconds > 0
      ? Math.min(retryAfterSeconds * 1_000, 30_000)
      : undefined,
  });
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
  let timedOut = false;
  const timeout = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort(new DOMException("Request timed out", "TimeoutError"));
  }, options.timeoutMs ?? 7_000);
  const abortFromCaller = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) abortFromCaller();
  else options.signal?.addEventListener("abort", abortFromCaller, { once: true });

  try {
    const requestHeaders = new Headers(options.headers);
    if (!requestHeaders.has("Accept")) requestHeaders.set("Accept", "application/json");
    const canonicalEndpoint = endpoint.split("?", 1)[0];
    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: options.method ?? "GET",
        headers: requestHeaders,
        body: options.body,
        signal: controller.signal,
      });
    } catch (error) {
      if (!timedOut) throw error;
      throw new ApiRequestError({
        endpoint: canonicalEndpoint,
        status: 0,
        code: "request_timeout",
        message: "The service did not respond before the request deadline.",
        retryable: true,
        category: "network",
      });
    }
    if (!response.ok) throw await errorFromResponse(response, canonicalEndpoint);
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.toLowerCase().includes("application/json")) {
      throw new ApiRequestError({
        endpoint: canonicalEndpoint,
        status: response.status,
        code: "invalid_response_content_type",
        message: "The service returned an unsupported response format.",
        traceId: response.headers.get("x-trace-id") || undefined,
        category: "contract",
      });
    }
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      throw new ApiRequestError({
        endpoint: canonicalEndpoint,
        status: response.status,
        code: "invalid_json_response",
        message: "The service returned malformed JSON.",
        traceId: response.headers.get("x-trace-id") || undefined,
        category: "contract",
      });
    }
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
