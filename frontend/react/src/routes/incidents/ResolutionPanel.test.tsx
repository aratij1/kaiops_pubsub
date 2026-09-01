// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResolutionPanel from "./ResolutionPanel";

afterEach(cleanup);

describe("ResolutionPanel", () => {
  it("explains the exact change, target, evidence basis, and safety gate", () => {
    render(
      <ResolutionPanel
        workflow={{
          recommendation: {
            recommended_action: "Restart the payments API",
            root_cause: "The service process stopped responding",
            impact: "Payment requests are failing",
          },
        }}
        alertRow={{ service: "payments-api", environment: "prod" }}
        confidenceScore={0.88}
        executionPlan={{
          requiresApproval: true,
          riskTier: "high",
          executionMode: "jenkins",
          target: "payments-api",
          expectedOutcome: "The payments API passes independent recovery validation.",
          readinessDecision: { decision_id: "decision-1", signature: "signed-value", state: "execution_eligible" },
        }}
        readinessChecks={[
          { id: "evidence", label: "Grounded evidence", detail: "Evidence threshold met.", passed: true },
          { id: "rollback", label: "Rollback", detail: "Rollback supplied.", passed: true },
        ]}
        onNavigateTab={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Remediation recommendation" })).toBeVisible();
    expect(screen.getByText("Restart the payments API")).toBeVisible();
    expect(screen.getByText("payments-api")).toBeVisible();
    expect(screen.getByText("Payment requests are failing")).toBeVisible();
    expect(screen.getByText("The payments API passes independent recovery validation.")).toBeVisible();
    expect(screen.getByText("Human approval required")).toBeVisible();
    expect(screen.getByText("Eligible for guarded approval")).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "Recommendation confidence" })).toHaveAttribute("aria-valuenow", "88");
  });

  it("does not claim readiness while a safeguard is missing", () => {
    render(<ResolutionPanel workflow={{ recommendation: { recommended_action: "Restart", root_cause: "Deadlock" } }} alertRow={{ service: "api" }} confidenceScore={0.9} executionPlan={{}} readinessChecks={[{ id: "rollback", label: "Rollback", detail: "No rollback supplied.", passed: false, action: "attach rollback instructions" }]} onNavigateTab={vi.fn()} />);
    expect(screen.getByText("Backend readiness required")).toBeVisible();
    expect(screen.getByText(/Not ready/)).toBeVisible();
    expect(screen.getByText(/attach rollback instructions/)).toBeVisible();
  });

  it("never claims approval eligibility from local fields without a signed backend receipt", () => {
    render(<ResolutionPanel workflow={{ recommendation: { recommended_action: "Restart", root_cause: "Deadlock" } }} alertRow={{ service: "api" }} confidenceScore={0.99} executionPlan={{ target: "api" }} readinessChecks={[{ id: "rollback", label: "Rollback", detail: "Ready.", passed: true }]} onNavigateTab={vi.fn()} />);
    expect(screen.queryByText("Eligible for guarded approval")).not.toBeInTheDocument();
    expect(screen.getByText("Signed backend readiness")).toBeVisible();
  });

  it("renders the typed evidence-to-recovery decision trace without exposing credentials", () => {
    render(<ResolutionPanel
      workflow={{
        recommendation: { recommended_action: "Restart revision", root_cause: "Connection pool exhaustion", metadata: {
          iterative_investigation: {
            outcome: "EVIDENCE_SUPPORTED",
            investigation_plan: { questions_to_answer: ["Did the pool exhaust after the deployment?"] },
            typed_hypotheses: [{ title: "The new revision exhausted its pool", status: "SUPPORTED", probability: 0.92, reasoning_summary: "Logs and metrics corroborate the causal sequence.", confidence_factors: { causal_strength: 0.18 }, confidence_penalties: {} }],
          },
          resolution_options: [{ option_id: "restart-revision", title: "Restart the unhealthy revision", risk_level: "MEDIUM", automation_eligibility: "HITL", reasoning: "Governed catalog match backed by the supported RCA." }],
        } },
        remediation_action: { parameters: { preflight_evidence: { status: "PASSED", dry_run_evidence_id: "preflight:abc" } } },
        resolution_report: { metadata: { outcome_validation: { outcome: "RECOVERED", closure_authorized: true, stability_window_seconds: 300, failed_checks: [], rollback: { disposition: "NOT_REQUIRED" } } } },
        evaluation: { report: { code_patch_proposals: [{ proposal_id: "patch-1", title: "Bound connection pool growth", explanation: "Review-only code proposal.", executable: false }], preventive_recommendations: [{ recommendation_id: "prevent-1", risk_signal: "Pool pressure rising", mode: "SHADOW", execution_authorized: false, recommended_review: "Review capacity." }], evidence_council: { disposition: "SUPPORTED" }, temporal_service_graph: { edges: [{ edge_id: "edge-1" }] } } },
      }}
      alertRow={{ service: "payments-api", environment: "prod" }}
      confidenceScore={0.92}
      executionPlan={{ target: "payments-api", catalogPlan: { actions: [{ target_resource_id: "payments-api", safety_binding: { credential: { reference: "vault://tenant-a/prod/remediator" }, blast_radius: { scope: "single-service", verified: true, unknown_dependencies: false }, preflight: { status: "PLANNED" } } }] } }}
      onNavigateTab={vi.fn()}
    />);

    expect(screen.getByRole("heading", { name: "Evidence-to-recovery controls" })).toBeVisible();
    expect(screen.getByText("The new revision exhausted its pool")).toBeVisible();
    expect(screen.getByText("Restart the unhealthy revision")).toBeInTheDocument();
    expect(screen.getByText("Scoped reference present")).toBeInTheDocument();
    expect(screen.queryByText("vault://tenant-a/prod/remediator")).not.toBeInTheDocument();
    expect(screen.getAllByText("RECOVERED").length).toBeGreaterThan(0);
    expect(screen.getByText("NOT REQUIRED")).toBeInTheDocument();
    expect(screen.getByText("Bound connection pool growth")).toBeInTheDocument();
    expect(screen.getByText("Human review required · not executable")).toBeInTheDocument();
    expect(screen.getByText("Pool pressure rising")).toBeInTheDocument();
    expect(screen.getByText("SHADOW · execution not authorized")).toBeInTheDocument();
  });
});
