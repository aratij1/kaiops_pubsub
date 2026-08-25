import { useMemo } from "react";
import { canonicalIncidentAnalysis, formatQualityPercent } from "../../appHelpers.jsx";

interface ExecutionPlan {
  requiresApproval?: boolean;
  riskTier?: string;
  executionMode?: string;
}

interface ResolutionPanelProps {
  workflow: any;
  alertRow: any;
  confidenceScore: number;
  executionPlan: ExecutionPlan;
  onNavigateTab: (tab: string) => void;
  embedded?: boolean;
}

export default function ResolutionPanel({
  workflow,
  alertRow,
  confidenceScore,
  executionPlan,
  onNavigateTab,
  embedded = false,
}: ResolutionPanelProps) {
  const analysis = useMemo(
    () => canonicalIncidentAnalysis(workflow, alertRow),
    [workflow, alertRow],
  );

  return (
    <section className="panel incident-workspace-section incident-resolution-section" role="tabpanel">
      <div className="panel-head">
        <div>
          <span className="workspace-section-number">04</span>
          <h3>Proposed remediation plan</h3>
          <p>Confirm the evidence-grounded response, scope, and risk before dry run and approval.</p>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <tbody>
            <tr><th>Probable Root Cause</th><td>{analysis.rootCause}</td></tr>
            <tr><th>Business Impact</th><td>{analysis.impact}</td></tr>
            <tr><th>Recommended Action</th><td>{analysis.action}</td></tr>
            <tr><th>Confidence</th><td>{formatQualityPercent(confidenceScore)}</td></tr>
            <tr><th>Approval Required</th><td>{executionPlan.requiresApproval ? "yes" : "no"}</td></tr>
            <tr><th>Risk Tier</th><td>{executionPlan.riskTier || "-"}</td></tr>
            <tr><th>Execution Mode</th><td>{executionPlan.executionMode || "-"}</td></tr>
          </tbody>
        </table>
      </div>
      {!embedded ? <div className="incident-section-actions">
        <button type="button" className="button-secondary" onClick={() => onNavigateTab("rca")}>
          Review RCA
        </button>
        <button
          type="button"
          className="button-primary"
          onClick={() => onNavigateTab("execution")}
        >
          Review script and decide
        </button>
      </div> : null}
    </section>
  );
}
