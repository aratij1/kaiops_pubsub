import { describe, expect, it } from "vitest";
import { friendlyLoginErrorMessage } from "./appHelpers.jsx";

describe("friendlyLoginErrorMessage", () => {
  it("replaces the raw backend_unavailable 503 JSON blob with a friendly message", () => {
    const error = new Error(
      'HTTP 503: {"detail":"Backend service is starting or unavailable. Retry after the service health check passes.","status":"backend_unavailable"}',
    );

    expect(friendlyLoginErrorMessage(error)).toBe(
      "The service is starting up. Please wait a moment and try again.",
    );
  });

  it("treats any 503 as a startup message even without the backend_unavailable status field", () => {
    const error = new Error('HTTP 503: {"detail":"Service Unavailable"}');

    expect(friendlyLoginErrorMessage(error)).toBe(
      "The service is starting up. Please wait a moment and try again.",
    );
  });

  it("strips the HTTP wrapper but keeps the backend's own readable detail for auth failures", () => {
    const error = new Error('HTTP 401: {"detail":"Invalid credentials"}');

    expect(friendlyLoginErrorMessage(error)).toBe("Invalid credentials");
  });

  it("strips the HTTP wrapper for account-lock responses", () => {
    const error = new Error('HTTP 423: {"detail":"Account is locked"}');

    expect(friendlyLoginErrorMessage(error)).toBe("Account is locked");
  });

  it("falls back to the raw body text when it is not JSON", () => {
    const error = new Error("HTTP 502: Bad Gateway");

    expect(friendlyLoginErrorMessage(error)).toBe("Bad Gateway");
  });

  it("passes through non-HTTP error messages unchanged (e.g. network failures)", () => {
    const error = new Error("Failed to reach http://localhost:8010. Open the UI through Docker/nginx.");

    expect(friendlyLoginErrorMessage(error)).toBe(
      "Failed to reach http://localhost:8010. Open the UI through Docker/nginx.",
    );
  });

  it("returns a generic message for an empty/missing error", () => {
    expect(friendlyLoginErrorMessage(new Error(""))).toBe("Sign in failed. Please try again.");
  });
});
