import { describe, expect, it } from "vitest";
import { approvalDecisionFields } from "./approvalDecisionPacket";

describe("approval decision packet", () => {
  it("extracts governed execution and recovery context", () => {
    const packet = approvalDecisionFields({ summary: "Checkout errors", projection_payload: { recommendation: { root_cause: "Pool exhaustion", metadata: { execution_plan: { capability_id: "kubernetes.restart", target_resource_id: "deployment/checkout", preconditions: ["replicas > 1"], validation_plan: { summary: "Probe for 5 minutes" }, rollback_plan: { summary: "Restore replica set" } } } } } });
    expect(packet.capability).toBe("kubernetes.restart"); expect(packet.exactTarget).toBe("deployment/checkout");
    expect(packet.preconditions).toEqual(["replicas > 1"]); expect(packet.validationPlan).toBe("Probe for 5 minutes"); expect(packet.rollbackPlan).toBe("Restore replica set");
  });
  it("marks absent decision evidence as not provided", () => { expect(approvalDecisionFields({}).diagnosis).toBe("Not provided"); });
});
