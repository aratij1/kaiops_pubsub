import { describe, expect, it } from "vitest";

import {
  canHydrateCompletedAnalysis,
  isExpectedAnalysisVersion,
  recommendationIdFromAnalysis,
} from "./analysisVersion";

describe("governed analysis version selection", () => {
  it("accepts only the recommendation generated for the active request", () => {
    const latest = { workflow: { recommendation: { id: "rca-v2" } } };

    expect(isExpectedAnalysisVersion(latest, "rca-v2")).toBe(true);
    expect(isExpectedAnalysisVersion(latest, "rca-v1")).toBe(false);
  });

  it("rejects missing identities instead of allowing stale UI replacement", () => {
    expect(isExpectedAnalysisVersion({ recommendation: {} }, "rca-v2")).toBe(false);
    expect(isExpectedAnalysisVersion({ recommendation: { id: "rca-v2" } }, "")).toBe(false);
    expect(recommendationIdFromAnalysis({ recommendation: { id: "rca-v2" } })).toBe("rca-v2");
  });

  it("hydrates the expected completed version even when the RCA is safely blocked", () => {
    const insufficientEvidence = {
      workflow: {
        recommendation: {
          id: "rca-v3",
          metadata: { rca_analysis: { status: "insufficient-evidence", evidence_used: [] } },
        },
      },
    };

    expect(canHydrateCompletedAnalysis(true, insufficientEvidence, "rca-v3")).toBe(true);
    expect(canHydrateCompletedAnalysis(false, insufficientEvidence, "rca-v3")).toBe(false);
    expect(canHydrateCompletedAnalysis(true, insufficientEvidence, "rca-v2")).toBe(false);
  });
});
