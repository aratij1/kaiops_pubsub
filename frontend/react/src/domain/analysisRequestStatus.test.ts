import { describe, expect, it } from "vitest";

import { analysisFailureMessage, analysisRequestOutcome } from "./analysisRequestStatus";

describe("analysisRequestOutcome", () => {
  it("accepts only the expected completed recommendation", () => {
    expect(analysisRequestOutcome({ status: "complete", ready: true, recommendation_id: "new" }, "new").ready).toBe(true);
    expect(analysisRequestOutcome({ status: "complete", ready: true, recommendation_id: "old" }, "new").ready).toBe(false);
  });

  it("recognizes persisted failure and timeout states", () => {
    expect(analysisRequestOutcome({ status: "failed", terminal: true }).terminalFailure).toBe(true);
    expect(analysisRequestOutcome({ status: "timed_out" }).terminalFailure).toBe(true);
  });

  it("preserves the backend reason and retry guidance", () => {
    expect(analysisFailureMessage({ status: "failed", terminal_reason: "Context collection failed", retryable: true }))
      .toBe("Analysis failed: Context collection failed Run fresh analysis again; active requests are safely coalesced.");
  });
});
