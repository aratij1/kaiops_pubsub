import { describe, expect, it } from "vitest";
import { canonicalIncidentEvidence } from "./incidentEvidence";

describe("canonical incident evidence", () => {
  it("does not fabricate evidence from documents or alert metadata", () => {
    const result = canonicalIncidentEvidence({ documents: [{ id: "doc-1" }], source_alert: { id: "alert-1" }, recommendation: { metadata: { rca_analysis: {} } } });
    expect(result.evidence).toEqual([]);
    expect(result.confidence).toBe(0);
    expect(result.executionReady).toBe(false);
  });

  it("permits execution navigation only for exact grounded backend readiness", () => {
    const result = canonicalIncidentEvidence({
      investigation_integrity: { status: "verified" },
      context: { metadata: { context_evidence: { metrics: [{ evidence_id: "metric-1", source_id: "prometheus", citation: "prometheus://query/1", freshness: "fresh", current_observation: true }] } } },
      recommendation: { confidence: .92, metadata: {
        rca_status: "grounded",
        rca_analysis: { evidence_used: ["metric-1"] },
        iterative_investigation: { status: "conclusive", conclusive: true, conclusion: { confidence: .92 } },
        execution_plan: { execution_ready: true, mutating: true, readiness_blocks: [] },
      } },
    });
    expect(result.evidence).toHaveLength(1);
    expect(result.evidence[0].accepted).toBe(true);
    expect(result.executionReady).toBe(true);
  });
});
