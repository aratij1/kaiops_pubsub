import { describe, expect, it } from "vitest";

import { effectiveExecutionStatus } from "./incidentStatus";

describe("effectiveExecutionStatus", () => {
  it("keeps an authoritative terminal failure even when a queue URL exists", () => {
    expect(effectiveExecutionStatus("failed", "execution_failed", "https://jenkins.example/queue/item/42/"))
      .toBe("execution_failed");
  });

  it("keeps a confirmed successful outcome terminal after leaving the queue", () => {
    expect(effectiveExecutionStatus("resolved", "succeeded", "https://jenkins.example/queue/item/42/"))
      .toBe("succeeded");
  });

  it("shows failure when there is no active queued submission", () => {
    expect(effectiveExecutionStatus("failed", "failed", "")).toBe("failed");
  });

  it("does not claim execution before the executor acknowledges it", () => {
    expect(effectiveExecutionStatus("remediating", "dispatching", "")).toBe("dispatching");
    expect(effectiveExecutionStatus("remediating", "executor_accepted", "https://jenkins.example/queue/item/42/"))
      .toBe("executor_accepted");
  });
});
