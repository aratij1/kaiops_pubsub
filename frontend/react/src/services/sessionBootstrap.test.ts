// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

import { restoreStoredSession } from "./oidcClient";
import { clearStoredSession, storeSessionTokens } from "./sessionBootstrap";

const localConfig = { mode: "local" as const, local_development_only: true, issuer: null, client_id: null, audience: null, pkce_required: false };

describe("authenticated session bootstrap", () => {
  beforeEach(() => clearStoredSession());

  it("rotates a stored refresh token and trusts the server-returned user", async () => {
    storeSessionTokens({ accessToken: "expired-access", refreshToken: "valid-refresh" });
    const request = vi.fn().mockResolvedValue({ access_token: "new-access", refresh_token: "new-refresh", user: { username: "admin", role_name: "Administrator" } });
    await expect(restoreStoredSession(localConfig, request)).resolves.toMatchObject({ accessToken: "new-access", refreshToken: "new-refresh", user: { username: "admin" } });
    expect(request).toHaveBeenCalledWith("/api-gateway/auth/refresh", expect.objectContaining({ method: "POST" }));
  });

  it("rejects expired or revoked sessions when the backend refresh fails", async () => {
    storeSessionTokens({ refreshToken: "revoked-refresh" });
    await expect(restoreStoredSession(localConfig, vi.fn().mockRejectedValue(new Error("HTTP 401")))).rejects.toThrow("HTTP 401");
  });

  it("does not invent a session when no server-verifiable token exists", async () => {
    await expect(restoreStoredSession(localConfig, vi.fn())).resolves.toBeNull();
  });
});
