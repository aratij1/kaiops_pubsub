import { useCallback, useEffect, useState } from "react";

import { useSession } from "../../app/SessionContext";
import { routeJson } from "../../services/routeApi";

type BusActivityRow = { service?: string; consumed?: string; published?: string; provider?: string; status?: string };
type BusTopologyRow = { service?: string; consumes?: string; publishes?: string };
type ModelProviderRow = { name: string; configured: boolean; healthy: boolean; model: string; circuitOpen: boolean; failures: number; reason: string };

type KnowledgeOverview = {
  actual: { rows: BusActivityRow[]; published: string[]; consumed: string[] };
  configuredRows: BusTopologyRow[];
  routing: { workflow?: string; next_action?: string } | null;
  primaryTopic: string;
  application: string;
  providers: ModelProviderRow[];
  providersLoading: boolean;
  providersError: string;
};

const EMPTY: KnowledgeOverview = {
  actual: { rows: [], published: [], consumed: [] },
  configuredRows: [],
  routing: null,
  primaryTopic: "",
  application: "Platform",
  providers: [],
  providersLoading: false,
  providersError: "",
};

function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function data(value: unknown): Record<string, unknown> {
  const root = object(value);
  return Object.keys(object(root.data)).length ? object(root.data) : root;
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error || "Request failed");
}

export function useKnowledgeOverview() {
  const { accessToken } = useSession();
  const [state, setState] = useState<KnowledgeOverview>(EMPTY);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!accessToken) {
      setState({ ...EMPTY, providersError: "Sign in to view provider and broker status." });
      return;
    }
    setState((current) => ({ ...current, providersLoading: true, providersError: "" }));
    const options = { signal, headers: { Authorization: `Bearer ${accessToken}` }, staleTimeMs: 0 };
    const [providerResult, queueResult] = await Promise.allSettled([
      routeJson<unknown>("/api-gateway/model/providers/status", options),
      routeJson<unknown>("/api-gateway/operations/queues", options),
    ]);
    if (signal?.aborted) return;
    const providerPayload = providerResult.status === "fulfilled" ? data(providerResult.value) : {};
    const providerMap = object(providerPayload.providers);
    const providers = Object.entries(providerMap).map(([name, raw]) => {
      const provider = object(raw);
      return {
        name,
        configured: Boolean(provider.configured),
        healthy: Boolean(provider.healthy),
        model: String(provider.model || name),
        circuitOpen: Boolean(provider.circuit_open),
        failures: Number(provider.failure_count || 0),
        reason: String(provider.reason || ""),
      };
    });
    const queuePayload = queueResult.status === "fulfilled" ? data(queueResult.value) : {};
    const queueRows = Array.isArray(queuePayload.queues) ? queuePayload.queues.map(object) : [];
    const consumed = queueRows.map((row) => String(row.name || "").trim()).filter(Boolean);
    const transport = String(object(queuePayload.summary).provider || queuePayload.provider || "Not reported");
    setState({
      actual: {
        rows: queueRows.map((row) => ({
          service: String(row.consumer || row.service || "Broker queue"),
          consumed: String(row.name || "Not reported"),
          published: "Not reported",
          provider: transport,
          status: "Observed",
        })),
        consumed,
        published: [],
      },
      configuredRows: [],
      routing: null,
      primaryTopic: consumed[0] || "",
      application: String(queuePayload.application || "Platform"),
      providers,
      providersLoading: false,
      providersError: [
        providerResult.status === "rejected" ? message(providerResult.reason) : "",
        queueResult.status === "rejected" ? message(queueResult.reason) : "",
      ].filter(Boolean).join("; "),
    });
  }, [accessToken]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  return { ...state, refresh: () => { void refresh(); }, refreshProviders: () => { void refresh(); } };
}
