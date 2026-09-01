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
  const recommendationMetadata = workflow?.recommendation?.metadata || {};
  const investigation = recommendationMetadata.iterative_investigation || recommendationMetadata.investigation_report || {};
  const hypotheses = Array.isArray(investigation.typed_hypotheses) ? investigation.typed_hypotheses : [];
  const questions = Array.isArray(investigation?.investigation_plan?.questions_to_answer) ? investigation.investigation_plan.questions_to_answer : [];
  const resolutionOptions = Array.isArray(recommendationMetadata.resolution_options) ? recommendationMetadata.resolution_options : [];
  const safetyBinding = typedAction?.safety_binding || {};
  const blastRadius = safetyBinding?.blast_radius || {};
  const preflight = workflow?.remediation_action?.parameters?.preflight_evidence || workflow?.remediation?.parameters?.preflight_evidence || safetyBinding?.preflight || {};
  const outcomeValidation = workflow?.resolution_report?.metadata?.outcome_validation || workflow?.closure_report?.metadata?.outcome_validation || workflow?.report?.metadata?.outcome_validation || {};
  const leadingHypothesis = hypotheses.find((item: any) => item.status === "SUPPORTED") || hypotheses[0];
  const confidenceFactors = leadingHypothesis?.confidence_factors && typeof leadingHypothesis.confidence_factors === "object" ? Object.entries(leadingHypothesis.confidence_factors) : [];
  const confidencePenalties = leadingHypothesis?.confidence_penalties && typeof leadingHypothesis.confidence_penalties === "object" ? Object.entries(leadingHypothesis.confidence_penalties) : [];
  const reviewArtifacts = workflow?.evaluation?.report || workflow?.evaluation_report?.report || recommendationMetadata;
  const patchProposals = Array.isArray(reviewArtifacts.code_patch_proposals) ? reviewArtifacts.code_patch_proposals : [];
  const preventiveRecommendations = Array.isArray(reviewArtifacts.preventive_recommendations) ? reviewArtifacts.preventive_recommendations : [];
  const evidenceCouncil = reviewArtifacts.evidence_council || {};
  const temporalGraph = reviewArtifacts.temporal_service_graph || {};
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

      <section className="autonomy-decision-details" aria-labelledby="autonomy-details-title">
        <header><div><span className="discovery-eyebrow">Decision trace</span><h4 id="autonomy-details-title">Evidence-to-recovery controls</h4></div><span className={`autonomy-outcome is-${String(outcomeValidation.outcome || investigation.outcome || "pending").toLowerCase().replaceAll("_", "-")}`}>{String(outcomeValidation.outcome || investigation.outcome || "Awaiting validation").replaceAll("_", " ")}</span></header>
        <div className="autonomy-detail-grid">
          <details open><summary>Investigation and hypotheses <small>{hypotheses.length} typed</small></summary><div className="autonomy-detail-body">{questions.length ? <ul className="autonomy-question-list">{questions.slice(0, 3).map((question: string) => <li key={question}>{question}</li>)}</ul> : <p>No typed investigation question was returned.</p>}{leadingHypothesis ? <article className="autonomy-highlight"><strong>{leadingHypothesis.title}</strong><span>{leadingHypothesis.status} · {formatQualityPercent(Number(leadingHypothesis.probability || 0))}</span><p>{leadingHypothesis.reasoning_summary || leadingHypothesis.description}</p><small>{Array.isArray(leadingHypothesis.supporting_evidence_ids) ? leadingHypothesis.supporting_evidence_ids.length : 0} supporting · {Array.isArray(leadingHypothesis.contradicting_evidence_ids) ? leadingHypothesis.contradicting_evidence_ids.length : 0} contradicting evidence records</small></article> : <p className="autonomy-empty">No causal hypothesis is available. Approval remains evidence-gated.</p>}{(confidenceFactors.length || confidencePenalties.length) ? <dl className="autonomy-factor-list">{confidenceFactors.slice(0, 4).map(([name, value]) => <div key={`factor-${name}`}><dt>{String(name).replaceAll("_", " ")}</dt><dd>+{formatQualityPercent(Number(value || 0))}</dd></div>)}{confidencePenalties.slice(0, 3).map(([name, value]) => <div key={`penalty-${name}`} className="is-penalty"><dt>{String(name).replaceAll("_", " ")}</dt><dd>−{formatQualityPercent(Number(value || 0))}</dd></div>)}</dl> : null}</div></details>
          <details><summary>Ranked resolution options <small>{resolutionOptions.length}</small></summary><div className="autonomy-detail-body">{resolutionOptions.length ? <ol className="autonomy-option-list">{resolutionOptions.map((option: any) => <li key={option.option_id}><strong>{option.title}</strong><span>{option.risk_level} risk · {option.automation_eligibility}</span><p>{option.reasoning}</p></li>)}</ol> : <p className="autonomy-empty">No governed option is available for this evidence state.</p>}</div></details>
          <details><summary>Blast radius and preflight <small>{preflight.status || "Not run"}</small></summary><div className="autonomy-detail-body"><dl className="autonomy-facts"><div><dt>Scope</dt><dd>{String(blastRadius.scope || "Unverified").replaceAll("-", " ")}</dd></div><div><dt>Verified</dt><dd>{blastRadius.verified === true ? "Yes" : "No"}</dd></div><div><dt>Dependencies</dt><dd>{blastRadius.unknown_dependencies === true ? "Unknown — blocked" : "Bounded"}</dd></div><div><dt>Preflight</dt><dd>{String(preflight.status || "Not run").replaceAll("_", " ")}</dd></div><div><dt>Dry-run evidence</dt><dd>{preflight.dry_run_evidence_id ? "Recorded" : "Required"}</dd></div><div><dt>Credential</dt><dd>{safetyBinding?.credential?.reference ? "Scoped reference present" : "Not verified"}</dd></div></dl></div></details>
          <details><summary>Validation and rollback <small>{outcomeValidation.rollback?.disposition || "Pending"}</small></summary><div className="autonomy-detail-body"><dl className="autonomy-facts"><div><dt>Recovery outcome</dt><dd>{String(outcomeValidation.outcome || "Not evaluated").replaceAll("_", " ")}</dd></div><div><dt>Closure authorized</dt><dd>{outcomeValidation.closure_authorized === true ? "Yes" : "No"}</dd></div><div><dt>Observation window</dt><dd>{outcomeValidation.stability_window_seconds ? `${outcomeValidation.stability_window_seconds}s` : "Pending"}</dd></div><div><dt>Rollback</dt><dd>{String(outcomeValidation.rollback?.disposition || "Pending").replaceAll("_", " ")}</dd></div></dl>{Array.isArray(outcomeValidation.failed_checks) && outcomeValidation.failed_checks.length ? <p className="autonomy-warning">Failed checks: {outcomeValidation.failed_checks.join(", ")}</p> : null}</div></details>
          <details><summary>Review-only intelligence <small>{patchProposals.length + preventiveRecommendations.length} artifacts</small></summary><div className="autonomy-detail-body"><dl className="autonomy-facts"><div><dt>Patch proposals</dt><dd>{patchProposals.length} · review only</dd></div><div><dt>Preventive recommendations</dt><dd>{preventiveRecommendations.length} · non-executing</dd></div><div><dt>Evidence council</dt><dd>{String(evidenceCouncil.disposition || "Not evaluated").replaceAll("_", " ")}</dd></div><div><dt>Temporal graph</dt><dd>{Array.isArray(temporalGraph.edges) ? `${temporalGraph.edges.length} evidence-bound edges` : "Not available"}</dd></div></dl>{patchProposals.slice(0, 2).map((proposal: any) => <article className="autonomy-highlight" key={proposal.proposal_id || proposal.title}><strong>{proposal.title}</strong><span>Human review required · not executable</span><p>{proposal.explanation}</p></article>)}{preventiveRecommendations.slice(0, 2).map((recommendation: any) => <article className="autonomy-highlight" key={recommendation.recommendation_id || recommendation.risk_signal}><strong>{recommendation.risk_signal}</strong><span>{recommendation.mode} · execution not authorized</span><p>{recommendation.recommended_review}</p></article>)}</div></details>
        </div>
      </section>

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
