import { describe, expect, it } from "vitest";

import { effectiveExecutionStatus } from "./incidentStatus";

describe("effectiveExecutionStatus", () => {
  it("shows an active Jenkins submission as queued despite a stale incident failure", () => {
    expect(effectiveExecutionStatus("failed", "failed", "https://jenkins.example/queue/item/42/"))
      .toBe("queued");
  });

  it("keeps a confirmed successful outcome terminal after leaving the queue", () => {
    expect(effectiveExecutionStatus("resolved", "succeeded", "https://jenkins.example/queue/item/42/"))
      .toBe("succeeded");
  });

  it("shows failure when there is no active queued submission", () => {
    expect(effectiveExecutionStatus("failed", "failed", "")).toBe("failed");
  });
});
