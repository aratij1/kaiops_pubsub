import { describe, expect, it } from "vitest";

import { dashboardAttentionRows, needsDashboardApproval } from "./DashboardRoute";

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

describe("dashboardAttentionRows", () => {
  it("renders critical incidents counted as attention and deduplicates higher-priority reasons", () => {
    const pending = { incident_id: "incident-1", severity: "critical" } as any;
    const criticalOnly = { incident_id: "incident-2", severity: "critical" } as any;
    const rows = dashboardAttentionRows([pending], [], [pending, criticalOnly]);

    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ row: pending, action: "Review decision" });
    expect(rows[1]).toMatchObject({ row: criticalOnly, action: "Review critical incident" });
  });
});
