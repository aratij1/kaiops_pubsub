import { describe, expect, it } from "vitest";

import { ApiValidationError } from "../services/apiClient";
import { internalApiContractCount, parseInternalApiResponse } from "./apiContracts";
import { OperationalEventSchema } from "./operationalEvents";
import { OidcDiscoverySchema, OidcTokenResponseSchema } from "./oidc";

describe("internal API contract registry", () => {
  it("covers every internal endpoint family and fails closed for unknown paths", () => {
    expect(internalApiContractCount).toBeGreaterThanOrEqual(19);
    expect(parseInternalApiResponse("/api-gateway/healthz", "GET", { status: "ok" })).toMatchObject({ status: "ok" });
    expect(parseInternalApiResponse("/api-gateway/operations/queue-health", "GET", {
      status: "healthy",
      provider: "rabbitmq",
      healthy: true,
      queues: 4,
      messages: 2,
      ready: 2,
      unacknowledged: 0,
    })).toMatchObject({ status: "healthy", healthy: true, queues: 4 });
    expect(parseInternalApiResponse("/api-gateway/incidents/metadata?limit=10", "GET", { rows: [] })).toMatchObject({ rows: [] });
    expect(parseInternalApiResponse("/api-gateway/evaluations/by-recommendation/1f11cbe9-274a-490a-ae4c-aebb3d70e58a/feedback", "POST", { updated: true })).toEqual({ updated: true });
    expect(() => parseInternalApiResponse("/api-gateway/unregistered", "GET", {})).toThrow(ApiValidationError);
  });

  it("rejects malformed authentication and streaming payloads", () => {
    expect(() => parseInternalApiResponse("/api-gateway/auth/login", "POST", { access_token: "" })).toThrow(ApiValidationError);
    expect(() => parseInternalApiResponse("/api-gateway/evaluations/by-recommendation/1f11cbe9-274a-490a-ae4c-aebb3d70e58a/feedback", "POST", { updated: "yes" })).toThrow(ApiValidationError);
    expect(OperationalEventSchema.safeParse({ id: "", type: "alert.created", data: {} }).success).toBe(false);
  });

  it("validates identity-provider discovery and token contracts", () => {
    expect(OidcDiscoverySchema.parse({ authorization_endpoint: "https://id.example/authorize", token_endpoint: "https://id.example/token" })).toBeTruthy();
    expect(OidcTokenResponseSchema.safeParse({ access_token: "" }).success).toBe(false);
  });
});
