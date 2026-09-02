import { useCallback, useEffect, useState } from "react";

import { useSession } from "../../app/SessionContext";
import { routeJson } from "../../services/routeApi";

export interface SafetySummary {
  total_events?: number;
  allowed?: number;
  blocked?: number;
  review?: number;
  latest_trace_id?: string;
}

export interface SafetyEventRow {
  created_at?: string;
  path?: string;
  status_code?: string | number;
  latency_ms?: number;
  trace_id?: string;
  safety?: { decision?: string; score?: number; reasons?: string[] };
}

export interface LandingPadRow {
  received_at?: string;
  modified_at?: string;
  name?: string;
  alertname?: string;
  service?: string;
  severity?: string;
  alert_status?: string;
  file?: string;
}

type SafetyData = {
  loading: boolean;
  summary: SafetySummary;
  summaryError: string;
  events: SafetyEventRow[];
  landingRows: LandingPadRow[];
  landingError: string;
};

const EMPTY: SafetyData = { loading: false, summary: {}, summaryError: "", events: [], landingRows: [], landingError: "" };

function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function data(value: unknown): Record<string, unknown> {
  const root = object(value);
  return Object.keys(object(root.data)).length ? object(root.data) : root;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || "Request failed");
}

export function useSafetyData() {
  const { accessToken } = useSession();
  const [state, setState] = useState<SafetyData>(EMPTY);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!accessToken) {
      setState({ ...EMPTY, summaryError: "Sign in to view governance telemetry.", landingError: "Sign in to view source intake." });
      return;
    }
    setState((current) => ({ ...current, loading: true }));
    const options = { signal, headers: { Authorization: `Bearer ${accessToken}` }, staleTimeMs: 0 };
    const [summaryResult, eventsResult, landingResult] = await Promise.allSettled([
      routeJson<unknown>("/api-gateway/observability/summary", options),
      routeJson<unknown>("/api-gateway/observability/recent?limit=120", options),
      routeJson<unknown>("/api-gateway/landing-pad/recent?limit=100", options),
    ]);
    if (signal?.aborted) return;
    const summaryPayload = summaryResult.status === "fulfilled" ? data(summaryResult.value) : {};
    const eventPayload = eventsResult.status === "fulfilled" ? data(eventsResult.value) : {};
    const landingPayload = landingResult.status === "fulfilled" ? data(landingResult.value) : {};
    setState({
      loading: false,
      summary: summaryPayload as SafetySummary,
      summaryError: summaryResult.status === "rejected" ? errorMessage(summaryResult.reason) : eventsResult.status === "rejected" ? errorMessage(eventsResult.reason) : "",
      events: Array.isArray(eventPayload.events) ? eventPayload.events as SafetyEventRow[] : [],
      landingRows: Array.isArray(landingPayload.rows) ? landingPayload.rows as LandingPadRow[] : [],
      landingError: landingResult.status === "rejected" ? errorMessage(landingResult.reason) : "",
    });
  }, [accessToken]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  return { ...state, refresh: () => { void refresh(); } };
}
