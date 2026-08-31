import { queryOptions } from "@tanstack/react-query";
import { ApplicationDetailRowsSchema, ApplicationMutationResponseSchema, ApplicationRowsSchema, ApplicationUpdateSchema, NewApplicationSchema, type ApplicationUpdate, type NewApplication } from "../schemas/applications";
import { ApiRequestError, getValidated, requestValidated } from "./apiClient";

const headers = (token: string) => ({ Authorization: `Bearer ${token}` });
export const applicationKeys = { all: ["applications"] as const, list: (token: string) => ["applications", "list", Boolean(token)] as const, detail: (id: string, kind: string) => ["applications", "detail", id, kind] as const };

export function applicationsQueryOptions(token: string) {
  return queryOptions({
    queryKey: applicationKeys.list(token),
    queryFn: ({ signal }) => getValidated("/api-gateway/applications", ApplicationRowsSchema, {
      signal,
      headers: headers(token),
      timeoutMs: 20_000,
    }),
    enabled: Boolean(token),
    refetchOnMount: "always",
    retry: (failureCount, error) => {
      if (failureCount >= 3) return false;
      if (!(error instanceof ApiRequestError)) return true;
      return error.retryable || [0, 404, 408, 425, 429, 502, 503, 504].includes(error.status);
    },
    retryDelay: (attempt) => Math.min(750 * (2 ** attempt), 5_000),
  });
}
export function applicationDetailsQueryOptions(token: string, id: string, kind: "history" | "validations" | "dashboards") { return queryOptions({ queryKey: applicationKeys.detail(id, kind), queryFn: ({ signal }) => getValidated(`/api-gateway/applications/${encodeURIComponent(id)}/${kind}`, ApplicationDetailRowsSchema, { signal, headers: headers(token) }), enabled: Boolean(token && id) }); }
export async function createApplication(token: string, input: NewApplication) { const payload = NewApplicationSchema.parse(input); return requestValidated("/api-gateway/applications", ApplicationMutationResponseSchema, { method: "POST", headers: { ...headers(token), "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }
export async function updateApplication(token: string, id: string, input: ApplicationUpdate) { const payload = ApplicationUpdateSchema.parse(input); return requestValidated(`/api-gateway/applications/${encodeURIComponent(id)}`, ApplicationMutationResponseSchema, { method: "PUT", headers: { ...headers(token), "Content-Type": "application/json" }, body: JSON.stringify(payload) }); }
export async function deleteApplication(token: string, id: string) { return requestValidated(`/api-gateway/applications/${encodeURIComponent(id)}`, ApplicationMutationResponseSchema, { method: "DELETE", headers: headers(token) }); }
export async function suppressObservedApplication(token: string, name: string) { return requestValidated(`/api-gateway/alerts/applications/${encodeURIComponent(name)}`, ApplicationMutationResponseSchema, { method: "DELETE", headers: headers(token) }); }
