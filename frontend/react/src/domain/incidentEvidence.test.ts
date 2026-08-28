import { describe, expect, it } from "vitest";
import { canonicalIncidentEvidence } from "./incidentEvidence";

describe("canonical incident evidence", () => {
  const readyContract = {
    contract_version: "kaiops.incident-investigation.v1",
    tenant_id: "tenant-a", project_id: "payments",
    incident_id: "10000000-0000-4000-8000-000000000001",
    alert_id: "10000000-0000-4000-8000-000000000002",
    analysis_request_id: "10000000-0000-4000-8000-000000000003",
    context_snapshot_id: "10000000-0000-4000-8000-000000000004",
    context_fingerprint: "a".repeat(64), context_contract_version: "kaiops.context.v2",
    context_collected_at: "2026-08-27T10:00:00Z", context_expires_at: "2026-08-27T11:00:00Z",
    context_quality: { evidence_count: 1, category_coverage: 1, freshness_score: 1, provenance_score: 1, independent_source_count: 1, direct_observation_count: 1, valid: true, blocking_reasons: [] },
    context_sources: [],
    context_evidence: [{ evidence_id: "metric-1", category: "metrics", source_id: "prometheus", connector: "prometheus", tenant_id: "tenant-a", project_id: "payments", service: "payments", collected_at: "2026-08-27T10:00:00Z", freshness: "fresh", provenance: {}, citation: "prometheus://query/1", epistemic_role: "current_observation", current_observation: true }],
    investigation_id: "10000000-0000-4000-8000-000000000005", investigation_status: "conclusive", investigation_conclusive: true,
    rca_version: 1, rca_status: "grounded", accepted_evidence_ids: ["metric-1"], missing_evidence: [], conflicting_evidence: [],
    recommendation_id: "10000000-0000-4000-8000-000000000006", resolution_plan_id: "10000000-0000-4000-8000-000000000007", plan_fingerprint: `sha256:${"b".repeat(64)}`,
    execution_ready: true, readiness_blocks: [], approval_status: "approved", remediation_status: "not_started", validation_status: "pending",
    readiness: { context_ready: true, rca_ready: true, resolution_ready: true, approval_ready: true, execution_ready: true, validation_ready: false, closure_ready: false, blocking_reasons: [] },
  };
  it("does not fabricate evidence from documents or alert metadata", () => {
    const result = canonicalIncidentEvidence({ documents: [{ id: "doc-1" }], source_alert: { id: "alert-1" }, recommendation: { metadata: { rca_analysis: {} } } });
    expect(result.evidence).toEqual([]);
    expect(result.confidence).toBe(0);
    expect(result.executionReady).toBe(false);
  });

  it("permits execution navigation only for exact grounded backend readiness", () => {
    const result = canonicalIncidentEvidence({
      investigation_integrity: { status: "verified" },
      incident_investigation: readyContract,
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
    expect(result.contextReady).toBe(true);
    expect(result.rcaReady).toBe(true);
    expect(result.resolutionReady).toBe(true);
    expect(result.approvalReady).toBe(true);
    expect(result.executionReady).toBe(true);
    expect(result.contractValid).toBe(true);
  });

  it("keeps collected context separate from evidence accepted by the RCA", () => {
    const result = canonicalIncidentEvidence({
      context: { metadata: { context_evidence: { metrics: [
        { evidence_id: "metric-1", source_id: "prometheus", freshness: "fresh" },
      ] } } },
      recommendation: { confidence: .74, metadata: {
        rca_status: "insufficient_evidence",
        rca_analysis: { evidence_used: [], missing_evidence: ["traces"], confidence_score: .35 },
      } },
    });
    expect(result.evidence).toHaveLength(1);
    expect(result.evidence[0].accepted).toBe(false);
    expect(result.acceptedEvidenceIds).toEqual([]);
    expect(result.confidence).toBe(.35);
    expect(result.confidenceGrounded).toBe(false);
    expect(result.grounded).toBe(false);
    expect(result.executionReady).toBe(false);
  });

  it("never accepts synthetic or missing citations as RCA support", () => {
    const result = canonicalIncidentEvidence({
      context: { metadata: { context_evidence: { logs: [
        { evidence_id: "log-1", source_id: "logs", citation: "context://incident/log-1", freshness: "fresh" },
      ] } } },
      recommendation: { metadata: {
        rca_status: "grounded",
        rca_analysis: { evidence_used: ["log-1"] },
      } },
    });
    expect(result.evidence[0].accepted).toBe(false);
    expect(result.grounded).toBe(false);
    expect(result.rcaReady).toBe(false);
  });

  it("opens resolution planning for grounded RCA before a plan exists", () => {
    const contract = {
      ...readyContract,
      resolution_plan_id: null,
      plan_fingerprint: null,
      execution_ready: false,
      readiness_blocks: ["exact resolution plan is not ready"],
      approval_status: "not_ready",
      readiness: {
        context_ready: true,
        rca_ready: true,
        resolution_ready: false,
        approval_ready: false,
        execution_ready: false,
        validation_ready: false,
        closure_ready: false,
        blocking_reasons: ["exact resolution plan is not ready"],
      },
    };
    const result = canonicalIncidentEvidence({
      investigation_integrity: { status: "verified" },
      incident_investigation: contract,
    });

    expect(result.rcaReady).toBe(true);
    expect(result.resolutionReady).toBe(false);
    expect(result.executionReady).toBe(false);
  });
});
