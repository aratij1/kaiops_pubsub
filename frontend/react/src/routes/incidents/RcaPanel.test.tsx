// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RcaPanel, {
  governedPlanFromWorkflow,
  governedPlanMatchesSelection,
  humanizeRcaHypothesis,
  resolutionBindingFor,
  resolutionSelectionPayload,
  staleApprovalEvidence,
} from "./RcaPanel";

vi.mock("../../app/routeRuntime", () => ({ useRouteRuntimeSlice: () => ({ accessToken: "test-token" }) }));

describe("RcaPanel canonical evidence gate", () => {
  it("does not treat unbound historical context as an approval freshness error", () => {
    expect(staleApprovalEvidence([
      { id: "history-1", accepted: false, cached: true, freshness: "stale" },
      { id: "metric-1", accepted: true, cached: false, freshness: "fresh" },
    ])).toEqual([]);
  });

  it("requires refresh when stale evidence is actually bound to the RCA", () => {
    expect(staleApprovalEvidence([
      { id: "metric-1", accepted: true, cached: true, freshness: "stale" },
    ])).toEqual([expect.objectContaining({ id: "metric-1" })]);
  });

  it("summarizes legacy structured metric hypotheses without raw JSON", () => {
    const result = humanizeRcaHypothesis('Observed signal requiring causal confirmation: {"source_status":"completed","query":"sum(rate(http_requests_total[5m]))","series":[{"metric":{"service":"checkout"}}],"provenance":{"source":"onboarded-prometheus"}}');
    expect(result).toBe("Observed signal requiring causal confirmation: Prometheus returned 1 time series for query: sum(rate(http_requests_total[5m]))");
    expect(result).not.toContain("source_status");
  });

  it("removes numbered connector payloads from impact and RCA summaries", () => {
    const result = humanizeRcaHypothesis('Observed technical impact: elevated latency affected api-gateway. 5 | "alert": { 6 | "source": "prometheus", 11 | "description": "Service api-gateway operation /configuration p99 latency is above 3s." Customer and business impact are not established by the available evidence.');

    expect(result).toContain("Observed technical impact: elevated latency affected api-gateway");
    expect(result).toContain("Service api-gateway operation /configuration p99 latency is above 3s.");
    expect(result).not.toContain('5 | "alert"');
  });

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
      selectedAiTrust={{ evidence: [], missing: [], conflicting: [], confidenceReasons: [], sources: {}, confidence: 0, contractPresent: false, contractValid: false, integrityVerified: false, executionReady: false }}
      selectedAlertWorkflow={{ recommendation: { metadata: {} }, context: { metadata: {} } }}
      selectedAlertRegeneration={{ loading: false }} selectedAlertRecommendationId="recommendation-1"
      selectedAlertDocumentContract={null} selectedAlertId="incident-1" aiFeedbackState={{}}
      rcaAnalysisMode="smart" onSetRcaAnalysisMode={vi.fn()} onRerunRca={vi.fn()}
      onRefreshSelectedAlert={vi.fn()}
      onDownloadRagDocument={vi.fn()} onLoadRagDocumentContent={vi.fn()}
      onSubmitAiRecommendationFeedback={vi.fn()}
    />);
    expect(screen.getByText("No observations are bound to this RCA snapshot.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Summary/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("Decision brief", { exact: true })).not.toBeInTheDocument();
    expect(screen.getAllByText("0%").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Investigation contract invalid at root/)).not.toBeInTheDocument();
    expect(screen.queryByText("Fresh context is required")).not.toBeInTheDocument();
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
    expect(screen.getAllByText("RCA readiness").length).toBeGreaterThan(0);
    expect(screen.getAllByText("46%").length).toBeGreaterThan(0);
    expect(screen.getByText(/RCA is not ready: 46% diagnostic readiness/)).toBeInTheDocument();
  });

  it("shows collected details but keeps remediation unavailable when RCA is inconclusive", () => {
    render(<RcaPanel
      rcaDetailView="evidence" onSetRcaDetailView={vi.fn()} onSetHomeDetailTab={vi.fn()}
      selectedAlertTimelineRows={[]} selectedAlertRagDocuments={[]} selectedAlertEvaluation={{}}
      selectedAlertRow={{ service: "api", tenant_id: "tenant-a" }}
      selectedRcaDecision={{ status: "insufficient-evidence", rootCause: "Investigation inconclusive", action: "Scale deployment" }}
      selectedAiTrust={{ evidence: [], missing: ["runbooks"], conflicting: [], confidenceReasons: [], sources: {}, confidence: .4, integrityVerified: true, rcaReady: false, executionReady: false }}
      selectedAlertWorkflow={{ recommendation: { metadata: {} }, context: { metadata: {
        context_quality: { contract_version: "kaiops.context.v2", quality_score: .79, rca_readiness_score: .49, provenance_score: .97, evidence_count: 1 },
        context_evidence: { telemetry: [{ evidence_id: "metric-1", source: "prometheus", summary: "p99 latency exceeded 3 seconds", observed_at: "2026-09-01T08:40:00Z" }] },
      } } }}
      selectedAlertRegeneration={{ loading: false }} selectedAlertRecommendationId="recommendation-1"
      selectedAlertDocumentContract={null} selectedAlertId="incident-1" aiFeedbackState={{}}
      rcaAnalysisMode="smart" onSetRcaAnalysisMode={vi.fn()} onRerunRca={vi.fn()}
      onRefreshSelectedAlert={vi.fn()} onDownloadRagDocument={vi.fn()}
      onLoadRagDocumentContent={vi.fn()} onSubmitAiRecommendationFeedback={vi.fn()}
    />);

    expect(screen.getByText("What the connectors observed")).toBeInTheDocument();
    expect(screen.getByText("p99 latency exceeded 3 seconds")).toBeInTheDocument();
    expect(screen.getAllByRole("tab", { name: /Evidence/ }).at(-1)).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByText("Open gaps").at(-1)?.nextElementSibling).toHaveTextContent("1");
    expect(screen.queryByRole("button", { name: "Remediation unavailable" })).not.toBeInTheDocument();
    expect(screen.queryByText("Scale deployment")).not.toBeInTheDocument();
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
