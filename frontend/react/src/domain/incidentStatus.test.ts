import { describe, expect, it } from "vitest";

import { decisionReadiness, effectiveExecutionStatus, executionProcessPresentation, incidentStatusLabel, userLifecycleStage } from "./incidentStatus";

describe("user lifecycle", () => {
  it("maps internal states to the five user-facing stages", () => {
    expect(userLifecycleStage("normalized")).toBe("triage");
    expect(userLifecycleStage("rca_ready")).toBe("investigate");
    expect(userLifecycleStage("awaiting_approval")).toBe("decide");
    expect(userLifecycleStage("executing")).toBe("act");
    expect(userLifecycleStage("validating")).toBe("verify");
  });

  it("blocks approval when confidence lacks grounded evidence", () => {
    expect(decisionReadiness({ citationCoverage: 0, evidenceCoverage: 0.9, runbookAvailable: true, preflightReady: true, rollbackAvailable: true }))
      .toMatchObject({ state: "not_ready", eligible: false, missing: ["supporting citations"] });
  });
});

describe("incidentStatusLabel", () => {
  it("turns internal lifecycle tokens into operator language", () => {
    expect(incidentStatusLabel("awaiting_approval")).toBe("Awaiting approval");
    expect(incidentStatusLabel("policy_blocked")).toBe("Waiting for approval");
  });
});

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

  it("treats diagnostic completion as a successful terminal outcome", () => {
    expect(effectiveExecutionStatus("closed", "diagnostic_completed", "")).toBe("succeeded");
  });

  it("presents a policy handoff as awaiting approval instead of a failed execution", () => {
    expect(effectiveExecutionStatus("awaiting_approval", "policy_blocked", ""))
      .toBe("awaiting_approval");
  });
});

describe("executionProcessPresentation", () => {
  it("does not let historical queue metadata override a terminal failure", () => {
    expect(executionProcessPresentation("execution_failed", undefined, true)).toMatchObject({
      failed: true,
      active: false,
      badgeLabel: "Failed",
      executionMode: "Failed",
      executionStageLabel: "Failed",
    });
  });

  it("keeps successful runs complete when submission metadata remains attached", () => {
    expect(executionProcessPresentation("succeeded", false, true)).toMatchObject({
      succeeded: true,
      active: false,
      badgeLabel: "Completed",
      executionMode: "Live",
    });
  });

  it("distinguishes queued and running executor states", () => {
    expect(executionProcessPresentation("executor_accepted", false, true).executionStageLabel).toBe("Build queued");
    expect(executionProcessPresentation("running", false, true).executionStageLabel).toBe("Build running");
  });
});
