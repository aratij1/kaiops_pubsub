import { describe, expect, it } from "vitest";
import { canonicalApprovalEligibility } from "./approvalEligibility";

const fingerprint = `sha256:${"a".repeat(64)}`;
const ready = {
  incident_investigation: { readiness: { approval_ready: true, blocking_reasons: [] }, readiness_blocks: [] },
  investigation_integrity: { status: "verified", verified: true, blocking_reasons: [] },
  recommendation: { id: "rec-1", metadata: { governed_resolution_plan: { plan_id: "plan-1", plan_fingerprint: fingerprint } } },
  approval_readiness: { decision_id: "decision-1", signature: "signed", state: "execution_eligible", plan_id: "plan-1", plan_fingerprint: fingerprint, recommendation_id: "rec-1" },
};

describe("canonicalApprovalEligibility", () => {
  it("requires the canonical contract, integrity, governed plan, and signed matching receipt", () => {
    expect(canonicalApprovalEligibility({ workflow: ready })).toMatchObject({ eligible: true, executionEligible: true });
  });

  it("fails closed when the signed receipt belongs to an older plan", () => {
    const result = canonicalApprovalEligibility({ workflow: { ...ready, approval_readiness: { ...ready.approval_readiness, plan_id: "old-plan" } } });
    expect(result.eligible).toBe(false);
    expect(result.reasons).toContain("approval-readiness receipt is stale for the current recommendation or plan");
    expect(result.canReject).toBe(true);
  });

  it("does not infer eligibility from complete-looking local plan fields", () => {
    const result = canonicalApprovalEligibility({ plan: { plan_id: "plan-1", plan_fingerprint: fingerprint } });
    expect(result.eligible).toBe(false);
    expect(result.receiptValid).toBe(false);
  });
});
