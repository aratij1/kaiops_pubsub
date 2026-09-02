import { describe, expect, it } from "vitest";

import { needsDashboardApproval } from "./DashboardRoute";

describe("needsDashboardApproval", () => {
  it("does not treat the configured human approval mode as a pending decision", () => {
    expect(needsDashboardApproval({ execution_mode: "human-approval", status: "investigating" })).toBe(false);
  });

  it("uses authoritative approval and incident states", () => {
    expect(needsDashboardApproval({ approval_status: "pending" })).toBe(true);
    expect(needsDashboardApproval({ status: "awaiting_approval" })).toBe(true);
    expect(needsDashboardApproval({ approval_status: "approved", status: "investigating" })).toBe(false);
  });
});