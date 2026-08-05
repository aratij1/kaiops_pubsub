import { queryOptions } from "@tanstack/react-query";

import { AlertRowsResponseSchema, type AlertRow } from "../schemas/alerts";
import { getValidated } from "./apiClient";
import { alertQueryKeys } from "./queryKeys";

function safeLimit(limit: number, maximum: number): number {
  return Math.max(1, Math.min(Math.trunc(limit), maximum));
}

export async function fetchAlertRows(limit: number, signal?: AbortSignal): Promise<AlertRow[]> {
  const normalizedLimit = safeLimit(limit, 200);
  return getValidated(
    `/api-gateway/alerts/all?limit=${normalizedLimit}`,
    AlertRowsResponseSchema,
    { signal, timeoutMs: 7_000 },
  );
}

export async function fetchLandingPadRows(limit: number, signal?: AbortSignal): Promise<AlertRow[]> {
  const normalizedLimit = safeLimit(limit, 300);
  return getValidated(
    `/api-gateway/landing-pad/recent?limit=${normalizedLimit}`,
    AlertRowsResponseSchema,
    { signal, timeoutMs: 6_000 },
  );
}

export function alertRowsQueryOptions(limit: number) {
  const normalizedLimit = safeLimit(limit, 200);
  return queryOptions({
    queryKey: alertQueryKeys.list(normalizedLimit),
    queryFn: ({ signal }) => fetchAlertRows(normalizedLimit, signal),
  });
}

export function landingPadRowsQueryOptions(limit: number) {
  const normalizedLimit = safeLimit(limit, 300);
  return queryOptions({
    queryKey: alertQueryKeys.landingPad(normalizedLimit),
    queryFn: ({ signal }) => fetchLandingPadRows(normalizedLimit, signal),
  });
}
