import { describe, expect, it } from "vitest";
import { buildAlertDocumentDraft } from "./alertDocumentDraft";

const input = {
  alertId: "alert-1",
  alert: { name: "Checkout failures", service: "checkout", environment: "production", severity: "high" },
  workflow: {},
  evidence: [{ id: "LOG-1", citation: "logs://checkout/1" }],
};

describe("RCA evidence drafts", () => {
  it("labels review-required analysis as an unverified hypothesis", () => {
    const content = buildAlertDocumentDraft({ ...input, decision: { rootCause: "Pool exhaustion", reviewRequired: true, confidence: .72 } });
    expect(content).toContain("Root cause hypothesis (unverified)");
    expect(content).toContain("additional operator verification is required before publication");
  });

  it("labels verified analysis as root cause analysis", () => {
    const content = buildAlertDocumentDraft({ ...input, decision: { rootCause: "Pool exhaustion", reviewRequired: false, confidence: .93 } });
    expect(content).toContain("## Root cause analysis");
    expect(content).not.toContain("hypothesis (unverified)");
  });
});
