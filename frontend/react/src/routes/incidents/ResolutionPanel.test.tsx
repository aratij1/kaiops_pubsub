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
});
