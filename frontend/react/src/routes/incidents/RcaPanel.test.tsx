// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RcaPanel, {
  governedPlanFromWorkflow,
  governedPlanMatchesSelection,
  resolutionBindingFor,
  resolutionSelectionPayload,
} from "./RcaPanel";

vi.mock("../../app/routeRuntime", () => ({ useRouteRuntimeSlice: () => ({ accessToken: "test-token" }) }));

describe("RcaPanel canonical evidence gate", () => {
  it("never substitutes the alert id for the canonical incident id", () => {
    const binding = resolutionBindingFor(
      { incident: { id: "incident-123" }, incident_investigation: { alert_id: "alert-456" } },
      "alert-456",
    );
    expect(binding.incident_id).toBe("incident-123");
    expect(binding.incident_id).not.toBe(binding.alert_id);
  });
  it("hydrates only a canonical governed plan", () => {
    const plan = { schema_version: "kaiops.governed-resolution-plan.v1", plan_id: "plan-1" };
    expect(governedPlanFromWorkflow({ recommendation: { metadata: { governed_resolution_plan: plan } } })).toEqual(plan);
    expect(governedPlanFromWorkflow({ recommendation: { metadata: { execution_plan: { plan_id: "legacy" } } } })).toBeNull();
  });
  it("rejects a refreshed projection with stale immutable identities", () => {
    const selected = {
      plan_id: "plan-1", plan_fingerprint: `sha256:${"a".repeat(64)}`,
      recommendation_id: "recommendation-1", rca_version: 2,
      context_snapshot_id: "snapshot-1", context_fingerprint: "b".repeat(64),
    };
    const workflow = {
      recommendation: { metadata: { governed_resolution_plan: { ...selected, schema_version: "kaiops.governed-resolution-plan.v1" } } },
      incident_investigation: {
        recommendation_id: "recommendation-1", rca_version: 2,
        context_snapshot_id: "snapshot-1", context_fingerprint: "b".repeat(64),
      },
    };
    expect(governedPlanMatchesSelection(workflow, selected)).toBe(true);
    expect(governedPlanMatchesSelection({
      ...workflow,
      incident_investigation: { ...workflow.incident_investigation, rca_version: 3 },
    }, selected)).toBe(false);
  });
  it("submits every immutable binding identity and no browser-generated fingerprint", () => {
    const binding = {
      incident_id: "incident-1", alert_id: "alert-1", analysis_request_id: "analysis-1",
      recommendation_id: "recommendation-1", rca_version: 4, context_snapshot_id: "snapshot-1",
      context_fingerprint: "c".repeat(64),
    };
    const payload = resolutionSelectionPayload(binding, { id: "option-1" }, "latency", "payments");
    expect(payload).toEqual({ ...binding, option_id: "option-1", issue: "latency", service: "payments" });
    expect(payload).not.toHaveProperty("plan_id");
    expect(payload).not.toHaveProperty("plan_fingerprint");
  });
  it("shows zero linked records and blocks remediation navigation without backend readiness", () => {
    render(<RcaPanel
      rcaDetailView="simple" onSetRcaDetailView={vi.fn()} onSetHomeDetailTab={vi.fn()}
      selectedAlertTimelineRows={[]} selectedAlertRagDocuments={[]} selectedAlertEvaluation={{}}
      selectedAlertRow={{ service: "api", tenant_id: "tenant-a" }}
      selectedRcaDecision={{ confidence: .91, rootCause: "Speculative cause", action: "Restart" }}
      selectedAiTrust={{ evidence: [], missing: [], conflicting: [], confidenceReasons: [], sources: {}, confidence: 0, integrityVerified: false, executionReady: false }}
      selectedAlertWorkflow={{ recommendation: { metadata: {} }, context: { metadata: {} } }}
      selectedAlertRegeneration={{ loading: false }} selectedAlertRecommendationId="recommendation-1"
      selectedAlertDocumentContract={null} selectedAlertId="incident-1" aiFeedbackState={{}}
      rcaAnalysisMode="smart" onSetRcaAnalysisMode={vi.fn()} onRerunRca={vi.fn()}
      onRefreshSelectedAlert={vi.fn()}
      onDownloadRagDocument={vi.fn()} onLoadRagDocumentContent={vi.fn()}
      onSubmitAiRecommendationFeedback={vi.fn()}
    />);
    expect(screen.getByText("No direct observations are linked.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Plan blocked by readiness" })).toBeDisabled();
    expect(screen.getAllByText("0%").length).toBeGreaterThan(0);
  });

  it("separates reusable-context quality from evidence coverage and RCA readiness", () => {
    render(<RcaPanel
      rcaDetailView="evidence" onSetRcaDetailView={vi.fn()} onSetHomeDetailTab={vi.fn()}
      selectedAlertTimelineRows={[]} selectedAlertRagDocuments={[]} selectedAlertEvaluation={{}}
      selectedAlertRow={{ service: "api", tenant_id: "tenant-a" }}
      selectedRcaDecision={{ confidence: .15, rootCause: "Investigation is inconclusive", action: "Collect evidence" }}
      selectedAiTrust={{ evidence: [], missing: [], conflicting: [], confidenceReasons: [], sources: {}, confidence: .15, integrityVerified: true, executionReady: false }}
      selectedAlertWorkflow={{ recommendation: { metadata: {} }, context: { metadata: { context_quality: {
        contract_version: "kaiops.context.v2", reusable: true, quality_score: .81,
        coverage_score: .85, source_coverage_score: .375, rca_readiness_score: .46,
        rca_ready: false, provenance_score: .91, evidence_count: 4,
      } } } }}
      selectedAlertRegeneration={{ loading: false }} selectedAlertRecommendationId="recommendation-1"
      selectedAlertDocumentContract={null} selectedAlertId="incident-1" aiFeedbackState={{}}
      rcaAnalysisMode="smart" onSetRcaAnalysisMode={vi.fn()} onRerunRca={vi.fn()}
      onRefreshSelectedAlert={vi.fn()} onDownloadRagDocument={vi.fn()}
      onLoadRagDocumentContent={vi.fn()} onSubmitAiRecommendationFeedback={vi.fn()}
    />);

    expect(screen.getByText("Context reusable")).toBeInTheDocument();
    expect(screen.getByText(/reuse quality, not RCA confidence/)).toBeInTheDocument();
    expect(screen.getByText("Evidence-plane coverage")).toBeInTheDocument();
    expect(screen.getByText("38%")).toBeInTheDocument();
    expect(screen.getByText("RCA readiness")).toBeInTheDocument();
    expect(screen.getByText("46%")).toBeInTheDocument();
    expect(screen.getByText(/RCA is not ready: 46% diagnostic readiness/)).toBeInTheDocument();
  });

  it("recovers an expired contract with an explicit fresh-context request", () => {
    const setMode = vi.fn();
    const rerun = vi.fn();
    render(<RcaPanel
      rcaDetailView="simple" onSetRcaDetailView={vi.fn()} onSetHomeDetailTab={vi.fn()}
      selectedAlertTimelineRows={[]} selectedAlertRagDocuments={[]} selectedAlertEvaluation={{}}
      selectedAlertRow={{ service: "api", tenant_id: "tenant-a" }}
      selectedRcaDecision={{ confidence: .4, rootCause: "Pending", action: "Collect evidence" }}
      selectedAiTrust={{ evidence: [], missing: [], conflicting: [], confidenceReasons: [], sources: {}, confidence: .4, contractValid: false, integrityVerified: false, integrity: { status: "context_expired" }, executionReady: false }}
      selectedAlertWorkflow={{ recommendation: { metadata: {} }, context: { metadata: {} } }}
      selectedAlertRegeneration={{ loading: false }} selectedAlertRecommendationId="recommendation-1"
      selectedAlertDocumentContract={null} selectedAlertId="alert-1" aiFeedbackState={{}}
      rcaAnalysisMode="smart" onSetRcaAnalysisMode={setMode} onRerunRca={rerun}
      onRefreshSelectedAlert={vi.fn()} onDownloadRagDocument={vi.fn()}
      onLoadRagDocumentContent={vi.fn()} onSubmitAiRecommendationFeedback={vi.fn()}
    />);

    const recovery = screen.getAllByRole("region", { name: "Recover investigation contract" }).at(-1)!;
    fireEvent.click(within(recovery).getByRole("button", { name: "Collect fresh context now" }));

    expect(setMode).toHaveBeenCalledWith("fresh");
    expect(rerun).toHaveBeenCalledWith("fresh");
  });
});
