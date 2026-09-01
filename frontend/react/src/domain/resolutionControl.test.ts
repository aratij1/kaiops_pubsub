import { describe, expect, it } from "vitest";
import { resolveResolutionControl } from "./resolutionControl";

describe("resolveResolutionControl", () => {
  it("prefers the authoritative control contract over contradictory legacy fields", () => {
    const result = resolveResolutionControl([{
      watch_only: true,
      metadata: { resolution_control: {
        schema_version: "kaims.resolution-control.v1",
        disposition: "approval_required",
        auto_close: false,
        approval_required: true,
        execution_allowed: false,
      } },
    }], { diagnosticOnly: false });
    expect(result.authoritative).toBe(true);
    expect(result.disposition).toBe("approval_required");
    expect(result.autoClose).toBe(false);
    expect(result.diagnosticOnly).toBe(false);
  });

  it("auto-closes an explicitly authorized watch-only decision", () => {
    const result = resolveResolutionControl([{
      resolution_lifecycle: { control: {
        schema_version: "kaims.resolution-control.v1",
        disposition: "watch_only",
        auto_close: true,
        watch_only_authorized: true,
        approval_required: false,
        execution_allowed: false,
      } },
    }]);
    expect(result.diagnosticOnly).toBe(true);
    expect(result.autoClose).toBe(true);
  });

  it("auto-closes a diagnostic legacy record", () => {
    const result = resolveResolutionControl([{ resolution_mode: "watch-only" }], { diagnosticOnly: true });
    expect(result.authoritative).toBe(false);
    expect(result.autoClose).toBe(true);
  });

  it("keeps a diagnostic legacy record open without explicit watch-only authorization", () => {
    const result = resolveResolutionControl([{}], { diagnosticOnly: true });
    expect(result.authoritative).toBe(false);
    expect(result.disposition).toBe("investigate");
    expect(result.autoClose).toBe(false);
  });

  it("does not interpret a generic no-action outcome as watch-only authorization", () => {
    const result = resolveResolutionControl([{ outcome: "no_action" }], { diagnosticOnly: true });
    expect(result.disposition).toBe("investigate");
    expect(result.autoClose).toBe(false);
  });

  it("does not auto-close a conflicting diagnostic control", () => {
    const result = resolveResolutionControl([{ resolution_control: {
      schema_version: "kaims.resolution-control.v1",
      disposition: "investigate",
      auto_close: false,
      conflicts: ["watch_only_cannot_include_executable_actions"],
    } }], { diagnosticOnly: true });
    expect(result.diagnosticOnly).toBe(true);
    expect(result.autoClose).toBe(false);
  });

  it("does not let UI diagnostic inference override an authoritative approval decision", () => {
    const result = resolveResolutionControl([{ resolution_control: {
      schema_version: "kaims.resolution-control.v1",
      disposition: "approval_required",
      auto_close: false,
      approval_required: true,
      execution_allowed: false,
    } }], { diagnosticOnly: true });
    expect(result.diagnosticOnly).toBe(false);
    expect(result.autoClose).toBe(false);
    expect(result.approvalRequired).toBe(true);
  });

  it("lets a finalized diagnostic contract supersede a stale approval decision", () => {
    const result = resolveResolutionControl([{ resolution_control: {
      schema_version: "kaims.resolution-control.v1",
      disposition: "approval_required",
      approval_required: true,
      execution_allowed: false,
      conflicts: [],
    } }], { diagnosticOnly: true, finalizedDiagnostic: true });
    expect(result.diagnosticOnly).toBe(true);
    expect(result.autoClose).toBe(false);
    expect(result.approvalRequired).toBe(false);
  });
});
