import { describe, expect, it } from "vitest";

import { IncidentInvestigationV1 } from "./incidentInvestigation";

const id = "00000000-0000-4000-8000-000000000001";

function payload() {
  return {
    contract_version: "kaiops.incident-investigation.v1",
    tenant_id: "tenant-a",
    project_id: "project-a",
    incident_id: id,
    alert_id: id,
    analysis_request_id: id,
    context_snapshot_id: id,
    context_fingerprint: "a".repeat(64),
    context_contract_version: "kaiops.context.v1",
    context_collected_at: "2026-08-27T10:00:00Z",
    context_expires_at: "2026-08-27T10:15:00Z",
    context_quality: { evidence_count: 0, category_coverage: 0, freshness_score: 0, provenance_score: 0, independent_source_count: 0, direct_observation_count: 0, valid: false, blocking_reasons: ["no_current_observations"] },
    context_sources: [],
    context_evidence: [],
    investigation_id: id,
    investigation_status: "inconclusive",
    investigation_conclusive: false,
    rca_version: 1,
    rca_status: "insufficient_evidence",
    accepted_evidence_ids: [],
    missing_evidence: ["service_telemetry"],
    conflicting_evidence: [],
    recommendation_id: null,
    resolution_plan_id: null,
    plan_fingerprint: null,
    execution_ready: false,
    readiness_blocks: ["insufficient_evidence"],
    approval_status: "not_ready",
    remediation_status: "not_started",
    validation_status: "not_started",
    readiness: { context_ready: false, rca_ready: false, resolution_ready: false, approval_ready: false, execution_ready: false, validation_ready: false, closure_ready: false, blocking_reasons: ["insufficient_evidence"] },
  };
}

describe("incident investigation v1", () => {
  it("accepts an explicit inconclusive state", () => {
    expect(IncidentInvestigationV1.parse(payload()).execution_ready).toBe(false);
  });

  it.each([
    ["unknown field", (value: any) => { value.undeclared = true; }],
    ["foreign evidence", (value: any) => { value.accepted_evidence_ids = ["not-in-snapshot"]; }],
    ["contradictory execution", (value: any) => { value.execution_ready = true; }],
    ["expired snapshot", (value: any) => { value.context_expires_at = value.context_collected_at; }],
  ])("rejects %s", (_name, mutate) => {
    const value = payload();
    mutate(value);
    expect(IncidentInvestigationV1.safeParse(value).success).toBe(false);
  });
});
