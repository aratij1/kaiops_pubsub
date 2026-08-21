import { useMemo } from "react";
import { CheckCircle2, ChevronRight, ShieldCheck, Target, TriangleAlert, Wrench } from "lucide-react";
import { canonicalIncidentAnalysis, formatQualityPercent } from "../../appHelpers.jsx";
import DecisionReadinessPanel, { type ReadinessCheck } from "./DecisionReadinessPanel";

interface ExecutionPlan {
  requiresApproval?: boolean;
  riskTier?: string;
  executionMode?: string;
  action?: string;
  target?: string;
  expectedOutcome?: string;
  catalogPlan?: any;
  readinessDecision?: any;
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
  const typedAction = Array.isArray(executionPlan.catalogPlan?.actions) ? executionPlan.catalogPlan.actions[0] : null;
  const target = executionPlan.target
    || executionPlan.catalogPlan?.remediation_target
    || typedAction?.target_resource_id
    || "Target not identified";
  const expectedOutcome = executionPlan.expectedOutcome
    || typedAction?.expected_outcome
    || "Independent recovery checks pass for the approved target.";
  const environment = alertRow?.environment || workflow?.incident?.environment || "Environment not identified";
  const readinessReceipt = executionPlan.readinessDecision
    || executionPlan.catalogPlan?.approval_readiness
    || workflow?.recommendation?.metadata?.approval_readiness
    || {};
  const backendEligibilityProven = Boolean(
    readinessReceipt.decision_id
    && readinessReceipt.signature
    && ["eligible", "execution_eligible"].includes(String(readinessReceipt.state || readinessReceipt.decision || "").toLowerCase())
  );
  const planComplete = Boolean(analysis.rootCause && analysis.rootCause !== "-" && action && action !== "-");
  const decisionChecks: ReadinessCheck[] = [
    ...readinessChecks,
    {
      id: "governed-target",
      label: "Governed target",
      detail: target !== "Target not identified" ? `Approved target: ${target}.` : "The approved plan has no typed target.",
      passed: target !== "Target not identified",
      action: "select a catalog plan with a typed target",
    },
    {
      id: "decision-confidence",
      label: "Evidence confidence",
      detail: `${confidencePercent}% evidence-derived confidence.`,
      passed: confidencePercent >= 85,
      action: "continue investigation until confidence reaches 85%",
    },
  ];
  const readinessComplete = decisionChecks.length > 0 && decisionChecks.every((check) => check.passed);
  const readyForDecision = planComplete && readinessComplete && backendEligibilityProven;

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
          {readyForDecision ? "Backend eligibility verified" : planComplete ? "Backend readiness required" : "Plan incomplete"}
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
              <div><dt>Current impact</dt><dd>{analysis.impact}</dd></div>
              <div><dt>Expected outcome</dt><dd>{expectedOutcome}</dd></div>
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
        checks={[...decisionChecks, {
          id: "backend-readiness-receipt",
          label: "Signed backend readiness",
          detail: backendEligibilityProven ? `Verified decision ${readinessReceipt.decision_id}.` : "No signed backend readiness decision proves execution eligibility.",
          passed: backendEligibilityProven,
          action: "request a fresh backend approval-readiness evaluation",
        }]}
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
