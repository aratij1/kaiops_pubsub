// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RcaPanel from "./RcaPanel";

vi.mock("../../app/routeRuntime", () => ({ useRouteRuntimeSlice: () => ({ accessToken: "test-token" }) }));

describe("RcaPanel canonical evidence gate", () => {
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
      onDownloadRagDocument={vi.fn()} onLoadRagDocumentContent={vi.fn()}
      onSubmitAiRecommendationFeedback={vi.fn()}
    />);
    expect(screen.getByText("No direct observations are linked.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Plan blocked by readiness" })).toBeDisabled();
    expect(screen.getAllByText("0%").length).toBeGreaterThan(0);
  });
});
