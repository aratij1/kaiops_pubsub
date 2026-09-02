// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ResolutionPanel from "./ResolutionPanel";
afterEach(cleanup);
const base = { alertRow: { service: "payments-api", environment: "prod" }, confidenceScore: .88, onNavigateTab: vi.fn() };
describe("ResolutionPanel", () => {
  it("shows exact governed scripts and the reason", () => {
    render(<ResolutionPanel {...base} workflow={{ investigation_integrity: { verified: true }, recommendation: { id: "rec-1", recommended_action: "Restart the unhealthy revision", root_cause: "Connection pool exhaustion is confirmed." } }} executionPlan={{ requiresApproval: true, riskTier: "high", executionMode: "jenkins", target: "payments-api", expectedOutcome: "Error rate returns below 1%.", catalogPlan: { plan_id: "p1", plan_fingerprint: `sha256:${"a".repeat(64)}`, recommendation_id: "rec-1", commands: ["kubectl rollout restart deployment/payments-api -n prod"], validation_commands: ["kubectl rollout status deployment/payments-api -n prod"], rollback_commands: ["kubectl rollout undo deployment/payments-api -n prod"] }, readinessDecision: { decision_id: "d1", signature: "signed", state: "execution_eligible", plan_id: "p1", plan_fingerprint: `sha256:${"a".repeat(64)}`, recommendation_id: "rec-1" } }} />);
    expect(screen.getByRole("heading", { name: "Review execution plan" })).toBeVisible();
    expect(screen.getByText("Connection pool exhaustion is confirmed.", { exact: false })).toBeVisible();
    expect(screen.getByText("kubectl rollout restart deployment/payments-api -n prod")).toBeVisible();
    expect(screen.getByText("kubectl rollout status deployment/payments-api -n prod")).toBeVisible();
    expect(screen.getByText("kubectl rollout undo deployment/payments-api -n prod")).toBeVisible();
  });
  it("does not fake a remediation script for evidence collection", () => {
    render(<ResolutionPanel {...base} workflow={{ recommendation: { recommended_action: "Collect traces evidence for this incident.", root_cause: "Causal confirmation is still required." } }} executionPlan={{ target: "payments-api" }} />);
    expect(screen.getByText("No executable remediation script is available")).toBeVisible();
    expect(screen.getByText(/close the evidence gaps/)).toBeVisible();
    expect(screen.getByRole("button", { name: /Inspect safeguards/ })).toBeDisabled();
  });
  it("labels model commands review-only", () => {
    render(<ResolutionPanel {...base} workflow={{ recommendation: { recommended_action: "Restart API", root_cause: "API stopped responding", metadata: { model_proposed_execution_plan: { commands: ["systemctl restart api"] } } } }} executionPlan={{ target: "api" }} />);
    expect(screen.getByText("Review-only model suggestion")).toBeVisible();
    expect(screen.getByText("systemctl restart api")).toBeInTheDocument();
    expect(screen.getByText(/not governed and cannot be executed/)).toBeInTheDocument();
  });
});
