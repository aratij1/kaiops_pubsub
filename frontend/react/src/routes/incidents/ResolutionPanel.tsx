import { useMemo } from "react";
import { CheckCircle2, ChevronRight, ShieldCheck, Target, TriangleAlert, Wrench } from "lucide-react";
import { canonicalIncidentAnalysis, formatQualityPercent } from "../../appHelpers.jsx";
import DecisionReadinessPanel, { type ReadinessCheck } from "./DecisionReadinessPanel";

interface ExecutionPlan {
  requiresApproval?: boolean;
  riskTier?: string;
  executionMode?: string;
  action?: string;
}

interface ResolutionPanelProps {
  workflow: any;
  alertRow: any;
  confidenceScore: number;
  executionPlan: ExecutionPlan;
  onNavigateTab: (tab: string) => void;
  embedded?: boolean;
  readinessChecks?: ReadinessCheck[];
}

export default function ResolutionPanel({
  workflow,
  alertRow,
  confidenceScore,
  executionPlan,
  onNavigateTab,
  embedded = false,
  readinessChecks = [],
}: ResolutionPanelProps) {
  const analysis = useMemo(() => canonicalIncidentAnalysis(workflow, alertRow), [workflow, alertRow]);
  const confidencePercent = Math.max(0, Math.min(100, Math.round(Number(confidenceScore || 0) * 100)));
  const riskTier = executionPlan.riskTier || "Not classified";
  const action = executionPlan.action && executionPlan.action !== "-" ? executionPlan.action : analysis.action;
  const target = alertRow?.service || alertRow?.application || workflow?.incident?.service || "Target not identified";
  const environment = alertRow?.environment || workflow?.incident?.environment || "Environment not identified";
  const planComplete = Boolean(analysis.rootCause && analysis.rootCause !== "-" && action && action !== "-");
  const readinessComplete = readinessChecks.length > 0 && readinessChecks.every((check) => check.passed);
  const readyForDecision = planComplete && confidencePercent > 0 && readinessComplete;

  return (
    <section className="panel incident-workspace-section incident-resolution-section resolution-decision-brief" role="tabpanel" aria-labelledby="resolution-recommendation-title">
      <header className="resolution-brief-header">
        <div>
          <span className="discovery-eyebrow">Resolution decision</span>
          <h3 id="resolution-recommendation-title">Remediation recommendation</h3>
          <p>Review the exact change, target, evidence basis, and safety envelope before approval.</p>
        </div>
        <span className={`decision-readiness ${readyForDecision ? "is-ready" : "is-blocked"}`}>
          {readyForDecision ? <CheckCircle2 size={17} /> : <TriangleAlert size={17} />}
          {readyForDecision ? "Ready for review" : planComplete ? "Evidence review required" : "Plan incomplete"}
        </span>
      </header>

      <div className="resolution-brief-layout">
        <article className="resolution-change-summary">
          <span className="resolution-brief-icon"><Wrench size={20} /></span>
          <div>
            <span className="resolution-brief-label">Proposed change</span>
            <h4>{action || "No corrective action has been proposed."}</h4>
            <dl>
              <div><dt>Target</dt><dd>{target}</dd></div>
              <div><dt>Environment</dt><dd>{environment}</dd></div>
              <div><dt>Expected outcome</dt><dd>{analysis.impact}</dd></div>
            </dl>
          </div>
        </article>

        <aside className="resolution-readiness-summary">
          <div className="decision-confidence">
            <div><span>AI confidence</span><strong>{formatQualityPercent(confidenceScore)}</strong></div>
            <div className="decision-confidence-track" role="progressbar" aria-label="Recommendation confidence" aria-valuemin={0} aria-valuemax={100} aria-valuenow={confidencePercent}><span style={{ width: `${confidencePercent}%` }} /></div>
            <small>Evidence support, not execution permission</small>
          </div>
          <dl className="decision-safety-facts">
            <div><dt>Approval gate</dt><dd>{executionPlan.requiresApproval ? "Human approval required" : "Policy controlled"}</dd></div>
            <div><dt>Risk tier</dt><dd>{riskTier}</dd></div>
            <div><dt>Executor</dt><dd>{executionPlan.executionMode || "Not configured"}</dd></div>
          </dl>
        </aside>
      </div>

      <div className="resolution-rationale-grid">
        <article>
          <span><Target size={17} /> Why this action</span>
          <strong>{analysis.rootCause}</strong>
          <p>The proposed change should address this leading cause. Validate the evidence and target before release.</p>
        </article>
        <article>
          <span><ShieldCheck size={17} /> What protects the service</span>
          <strong>Approval, idempotency, rollback, and recovery checks</strong>
          <p>The execution workspace shows any missing safeguard as a blocker before the primary action becomes available.</p>
        </article>
      </div>

      <DecisionReadinessPanel
        title="Approval eligibility"
        checks={readinessChecks}
        eligibleLabel="Eligible for guarded approval"
        onReviewEvidence={() => onNavigateTab("evidence")}
      />

      {!embedded ? <footer className="incident-section-actions resolution-brief-actions">
        <button type="button" className="button-secondary" onClick={() => onNavigateTab("rca")}>Review supporting evidence</button>
        <button type="button" className="button-primary" onClick={() => onNavigateTab("execution")}>Inspect safeguards and decide <ChevronRight size={16} /></button>
      </footer> : null}
    </section>
  );
}
