import { AlertTriangle, Home, RefreshCw } from "lucide-react";
import { isRouteErrorResponse, useRouteError } from "react-router-dom";

import { ApiRequestError, ApiValidationError } from "../services/apiClient";

function errorReference() {
  try {
    if (typeof globalThis.crypto?.randomUUID === "function") {
      return globalThis.crypto.randomUUID().slice(0, 8);
    }
  } catch {
    // randomUUID is unavailable in some non-secure browser contexts. A support
    // reference is diagnostic rather than security-sensitive, so keep the
    // fallback boundary renderable instead of throwing a second error.
  }
  return Math.random().toString(36).slice(2, 10).padEnd(8, "0");
}

function errorPresentation(error: unknown) {
  if (error instanceof ApiValidationError) {
    return { title: "Unexpected service response", message: "KaiMS protected this view because the returned data did not match its contract.", traceId: undefined };
  }
  if (error instanceof ApiRequestError) {
    return { title: error.retryable ? "Service temporarily unavailable" : "Request could not be completed", message: error.message, traceId: error.traceId };
  }
  if (isRouteErrorResponse(error)) {
    return { title: `Workspace error ${error.status}`, message: error.statusText || "The requested workspace could not be loaded.", traceId: undefined };
  }
  if (error instanceof Error) {
    const reference = errorReference();
    console.error(`[workspace-error:${reference}]`, error);
    return {
      title: "Workspace could not be displayed",
      message: `An unexpected interface error occurred. Retry the workspace. If it continues, provide reference ${reference} to support.`,
      traceId: undefined,
    };
  }
  return { title: "Workspace could not be displayed", message: "An unexpected interface error occurred. Reload the workspace or return to the command center.", traceId: undefined };
}

export function RouteErrorBoundary() {
  const presentation = errorPresentation(useRouteError());
  return (
    <main className="route-error-boundary" role="alert">
      <div className="route-error-mark"><AlertTriangle aria-hidden="true" /></div>
      <span className="route-error-eyebrow">Safe fallback</span>
      <h1>{presentation.title}</h1>
      <p>{presentation.message}</p>
      {presentation.traceId ? <code>Trace {presentation.traceId}</code> : null}
      <div>
        <button type="button" className="button-primary" onClick={() => window.location.reload()}><RefreshCw />Retry workspace</button>
        <a className="button-secondary" href="/"><Home />Command center</a>
      </div>
    </main>
  );
}
