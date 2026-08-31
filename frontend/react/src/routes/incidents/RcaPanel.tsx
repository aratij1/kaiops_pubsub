import { useEffect, useMemo, useState } from "react";
import {
  Activity, BookOpen, CheckCircle2, Clock3, Code2, Database, FileSearch,
  GitCommit, Network, RotateCw, Search, ShieldAlert, Sparkles,
} from "lucide-react";
import {
  canonicalIncidentAnalysis, formatQualityPercent, formatUtcTimestamp,
  normalizeAlertChannel, qualityToneFromScore, sourceChannelLabel,
  IntelligenceConnectionView, DiscoveryFlowView, ContextRetrievalGraph, fetchJson,
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-ignore - appHelpers.jsx is untyped legacy JS, no .d.ts yet.
} from "../../appHelpers.jsx";
import { useRouteRuntimeSlice } from "../../app/routeRuntime";
import EvidenceDraftReview from "./EvidenceDraftReview";
import DecisionReadinessPanel from "./DecisionReadinessPanel";
import ContextEnrichmentPanel from "./ContextEnrichmentPanel";
import "./RcaPanel.css";
import "./RcaReuseBanner.css";
import "./EvidenceReview.css";

type RcaDetailView = "simple" | "detailed" | "evidence" | "technical";

const EVIDENCE_SOURCE_DEFINITIONS = [
  { id: "metrics", label: "Metrics", icon: Activity, match: /prometheus|metric/i },
  { id: "logs", label: "Logs", icon: FileSearch, match: /log|opensearch|elastic/i },
  { id: "traces", label: "Traces", icon: Network, match: /trace|jaeger|span/i },
  { id: "changes", label: "Changes", icon: GitCommit, match: /deploy|change|commit|git/i },
  { id: "code", label: "Source code", icon: Code2, match: /code|source/i },
  { id: "knowledge", label: "Knowledge", icon: BookOpen, match: /rag|runbook|ticket|jira|document/i },
] as const;

const RCA_VIEWS: Array<{ id: RcaDetailView; label: string; description: string }> = [
  { id: "simple", label: "Decision brief", description: "Cause, impact, and next action" },
  { id: "evidence", label: "Evidence", description: "Sources, freshness, and citations" },
  { id: "detailed", label: "Analysis", description: "Causal reasoning and options" },
  { id: "technical", label: "Technical trace", description: "Queries, retrieval, and handoffs" },
];

export function resolutionBindingFor(workflow: any, selectedAlertId: string | null | undefined) {
  const contract = workflow?.incident_investigation || {};
  return {
    incident_id: contract.incident_id || workflow?.incident?.id || "",
    alert_id: contract.alert_id || selectedAlertId || "",
    analysis_request_id: contract.analysis_request_id || "",
    recommendation_id: contract.recommendation_id || "",
    rca_version: contract.rca_version || 0,
    context_snapshot_id: contract.context_snapshot_id || "",
    context_fingerprint: contract.context_fingerprint || "",
  };
}

export function governedPlanFromWorkflow(workflow: any) {
  const metadata = workflow?.recommendation?.metadata || {};
  const candidate = metadata.governed_resolution_plan || metadata.execution_plan || {};
  return candidate?.schema_version === "kaiops.governed-resolution-plan.v1" ? candidate : null;
}

export function governedPlanMatchesSelection(workflow: any, selected: any) {
  const plan = governedPlanFromWorkflow(workflow);
  const contract = workflow?.incident_investigation || {};
  return Boolean(
    plan
    && selected?.plan_id
    && plan.plan_id === selected.plan_id
    && plan.plan_fingerprint === selected.plan_fingerprint
    && plan.recommendation_id === selected.recommendation_id
    && contract.recommendation_id === selected.recommendation_id
    && Number(contract.rca_version) === Number(selected.rca_version)
    && contract.context_snapshot_id === selected.context_snapshot_id
    && contract.context_fingerprint === selected.context_fingerprint
  );
}

export function resolutionSelectionPayload(binding: any, option: any, issue: string, service: string) {
  return {
    incident_id: binding.incident_id,
    alert_id: binding.alert_id,
    analysis_request_id: binding.analysis_request_id,
    recommendation_id: binding.recommendation_id,
    rca_version: binding.rca_version,
    context_snapshot_id: binding.context_snapshot_id,
    context_fingerprint: binding.context_fingerprint,
    option_id: option.id,
    issue,
    service,
  };
}

interface RcaPanelProps {
  rcaDetailView: RcaDetailView;
  onSetRcaDetailView: (view: RcaDetailView) => void;
  onSetHomeDetailTab: (tab: string) => void;
  selectedAlertTimelineRows: any[];
  selectedAlertRagDocuments: any[];
  selectedAlertEvaluation: any;
  selectedAlertRow: any;
  selectedRcaDecision: any;
  selectedAiTrust: any;
  selectedAlertWorkflow: any;
  selectedAlertRegeneration: any;
  selectedAlertRecommendationId: string | null | undefined;
  selectedAlertDocumentContract: any;
  selectedAlertId: string | null | undefined;
  aiFeedbackState: any;
  rcaAnalysisMode: "smart" | "fresh" | "cache";
  onSetRcaAnalysisMode: (mode: "smart" | "fresh" | "cache") => void;
  onRerunRca: (modeOverride?: "smart" | "fresh" | "cache") => any;
  onRefreshSelectedAlert: () => Promise<any>;
  onDownloadRagDocument: (...args: any[]) => any;
  onLoadRagDocumentContent: (...args: any[]) => any;
  onSubmitAiRecommendationFeedback: (feedback: Record<string, string> | string) => any;
}

export default function RcaPanel({
  rcaDetailView, onSetRcaDetailView, onSetHomeDetailTab,
  selectedAlertTimelineRows, selectedAlertRagDocuments, selectedAlertEvaluation,
  selectedAlertRow, selectedRcaDecision, selectedAiTrust, selectedAlertWorkflow,
  selectedAlertRegeneration, selectedAlertRecommendationId, selectedAlertDocumentContract,
  selectedAlertId, aiFeedbackState, rcaAnalysisMode, onSetRcaAnalysisMode,
  onRerunRca, onRefreshSelectedAlert, onDownloadRagDocument, onLoadRagDocumentContent,
  onSubmitAiRecommendationFeedback,
}: RcaPanelProps) {
  const { accessToken } = useRouteRuntimeSlice("session");
  const integrityStatus = String(selectedAiTrust?.integrity?.status || "").trim().toLowerCase();
  const requiresFreshRecovery = selectedAiTrust?.contractValid !== true
    || ["context_expired", "missing_snapshot_reference", "snapshot_not_found"].includes(integrityStatus);
  const [resolutionOptions, setResolutionOptions] = useState<any[]>([]);
  const [pendingPlanId, setPendingPlanId] = useState("");
  const [resolutionStatus, setResolutionStatus] = useState("");
  const [feedbackDraft, setFeedbackDraft] = useState({ decision: "", reason_category: "", corrected_cause: "", missing_evidence: "", comment: "" });
  const recommendationMetadata = selectedAlertWorkflow?.recommendation?.metadata || {};
  const selectedResolution = governedPlanFromWorkflow(selectedAlertWorkflow);
  const investigationContract = selectedAlertWorkflow?.incident_investigation || {};
  const resolutionBinding = useMemo(() => resolutionBindingFor(selectedAlertWorkflow, selectedAlertId), [
    investigationContract.incident_id, investigationContract.alert_id,
    investigationContract.analysis_request_id, investigationContract.recommendation_id,
    investigationContract.rca_version, investigationContract.context_snapshot_id,
    investigationContract.context_fingerprint, selectedAlertWorkflow?.incident?.id, selectedAlertId,
  ]);
  const contextMetadata = selectedAlertWorkflow?.context?.metadata || {};
  const contextQuality = contextMetadata?.context_quality || {};
  const contextSourceManifest = selectedAiTrust?.sources || contextMetadata?.context_sources || {};
  const contextSourceRows = Object.entries(contextSourceManifest).map(([source, details]: [string, any]) => ({
    source,
    status: String(details?.status || details?.collection_status || "unknown"),
    count: Number(details?.result_count || 0),
    inferredTimestamps: Number(details?.inferred_timestamp_count || 0),
    attempted: details?.attempted !== false,
    lastAttempt: details?.last_attempt_at || details?.collected_at || "",
    error: String(details?.error || ""),
    requiredConfiguration: String(details?.required_configuration || ""),
  }));
  const evidenceRows = Array.isArray(selectedAiTrust?.evidence) ? selectedAiTrust.evidence : [];
  const supportingEvidenceRows = evidenceRows.filter((row: any) => row.accepted === true);
  const missingEvidence = Array.isArray(selectedAiTrust?.missing) ? selectedAiTrust.missing : [];
  const conflictingEvidence = Array.isArray(selectedAiTrust?.conflicting) ? selectedAiTrust.conflicting : [];
  const confidenceReasons = Array.isArray(selectedAiTrust?.confidenceReasons) ? selectedAiTrust.confidenceReasons : [];
  const impactedServices = Array.isArray(selectedRcaDecision?.impactedServices) ? selectedRcaDecision.impactedServices : [];
  const impactEvidence = Array.isArray(selectedRcaDecision?.impactEvidence) ? selectedRcaDecision.impactEvidence : [];
  const inferredContextTimestamps = contextSourceRows.reduce((total, source) => total + source.inferredTimestamps, 0);
  const sourceCoverageScore = Number(contextQuality?.source_coverage_score ?? contextQuality?.coverage_score ?? 0);
  const rcaReadinessScore = Number(contextQuality?.rca_readiness_score || 0);
  const freshEvidenceCount = evidenceRows.filter((row: any) => !row.cached).length;
  const cachedEvidenceCount = evidenceRows.length - freshEvidenceCount;
  const investigationReport = recommendationMetadata?.investigation_report
    || recommendationMetadata?.iterative_investigation
    || {};
  const investigationConfidence = Number(investigationReport?.conclusion?.confidence || 0);
  const investigationConclusive = investigationReport?.conclusive === true
    && String(investigationReport?.status || "").toLowerCase() === "conclusive";
  const groundingScore = Number(selectedAlertEvaluation?.groundingScore || 0);
  const confidence = Number(selectedAiTrust?.confidence || 0);
  const confidencePercent = Math.max(0, Math.min(100, Math.round(confidence * 100)));
  const confidenceLabel = String(selectedAiTrust?.confidenceLabel || "Leading hypothesis confidence");
  const reviewRequired = Boolean(
    selectedRcaDecision?.reviewRequired
    || missingEvidence.length
    || conflictingEvidence.length
    || evidenceRows.length === 0
    || selectedAiTrust?.integrityVerified !== true
    || !investigationConclusive
    || investigationConfidence < 0.85
    || groundingScore < 0.85
  );
  const decisionTone = confidence >= 0.85 ? "high" : confidence >= 0.7 ? "medium" : "low";
  const decisionStatus = reviewRequired ? "Review required" : "Investigation conclusive";
  const analysisReused = Boolean(recommendationMetadata.analysis_reused);
  const analysisReuseScore = Number(recommendationMetadata.analysis_reuse_score || 0);
  const discoveryAnalysis = recommendationMetadata?.discovery_report?.report
    || selectedAlertWorkflow?.context?.metadata?.discovery_report?.report || {};
  const proposedCodeChanges = Array.isArray(recommendationMetadata?.proposed_code_changes)
    ? recommendationMetadata.proposed_code_changes
    : Array.isArray(discoveryAnalysis?.proposed_code_changes) ? discoveryAnalysis.proposed_code_changes : [];
  const resolutionService = selectedAlertRow?.service || selectedAlertRow?.application || "unknown";
  const evidenceSources = useMemo(() => EVIDENCE_SOURCE_DEFINITIONS.map((source) => {
    let count = 0;
    let fresh = 0;
    for (const row of evidenceRows) {
      if (!source.match.test(`${row.source || ""} ${row.citation || ""}`)) continue;
      count += 1;
      if (!row.cached) fresh += 1;
    }
    return { ...source, count, fresh };
  }), [evidenceRows]);
  const connectedEvidenceSources = evidenceSources.filter((source) => source.count).length;
  const sourceChannel = Array.isArray(selectedAlertRow?.source_channels)
    ? selectedAlertRow.source_channels.map(sourceChannelLabel).join(" + ")
    : sourceChannelLabel(normalizeAlertChannel(selectedAlertRow));
  const citationCount = evidenceRows.filter((row: any) => String(row.citation || "").trim()).length;
  const investigationChecks = [
    { id: "evidence", label: "Linked observations", detail: evidenceRows.length ? `${evidenceRows.length} context observation(s) linked; ${supportingEvidenceRows.length} accepted as RCA support.` : "No direct observations are linked.", passed: evidenceRows.length > 0, action: "collect metrics, logs, traces, or change evidence" },
    { id: "citations", label: "Traceable citations", detail: citationCount ? `${citationCount} record(s) have a traceable citation.` : "No source citations were supplied.", passed: citationCount > 0, action: "attach source citations" },
    { id: "freshness", label: "Current evidence", detail: freshEvidenceCount ? `${freshEvidenceCount} live record(s) are available.` : "All evidence is cached or freshness is unknown.", passed: freshEvidenceCount > 0, action: "refresh incident context" },
    { id: "conflicts", label: "Conflicts resolved", detail: conflictingEvidence.length ? `${conflictingEvidence.length} conflict(s) require operator review.` : "No conflicting evidence was declared.", passed: conflictingEvidence.length === 0, action: "resolve conflicting observations" },
    { id: "gaps", label: "Declared gaps addressed", detail: missingEvidence.length ? missingEvidence.join(", ") : "The analysis declares no missing evidence.", passed: missingEvidence.length === 0, action: "collect the declared missing evidence" },
    { id: "investigation", label: "Iterative investigation", detail: investigationConclusive ? "The bounded investigation reached a corroborated conclusion." : "The investigation is missing or inconclusive.", passed: investigationConclusive, action: "continue the read-only investigation" },
    { id: "confidence", label: "Evidence confidence", detail: `${formatQualityPercent(investigationConfidence)} investigation confidence.`, passed: investigationConfidence >= 0.85, action: "raise evidence-derived confidence to at least 85%" },
    { id: "grounding", label: "Grounding coverage", detail: `${formatQualityPercent(groundingScore)} grounding coverage.`, passed: groundingScore >= 0.85, action: "raise grounding coverage to at least 85%" },
  ];

  useEffect(() => {
    let active = true;
    setPendingPlanId("");
    setResolutionStatus("");
    if (selectedAiTrust?.rcaReady !== true) {
      setResolutionOptions([]);
      setResolutionStatus("Resolution actions remain blocked until backend investigation readiness is verified.");
      return () => { active = false; };
    }
    fetchJson("/api-gateway/analysis/resolution-catalog/relevant", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({
        ...resolutionBinding,
        issue: selectedRcaDecision?.rootCause,
        service: resolutionService,
        recommended_action: selectedRcaDecision?.action,
      }),
      timeoutMs: 10000,
    }).then((response: any) => {
      const result = response?.data || response || {};
      if (active) setResolutionOptions(Array.isArray(result?.rows) ? result.rows : []);
    }).catch(() => {
      if (active) setResolutionStatus("Resolution options are temporarily unavailable.");
    });
    return () => { active = false; };
  }, [accessToken, selectedAlertId, selectedRcaDecision?.rootCause, selectedRcaDecision?.action, resolutionBinding, resolutionService, selectedAiTrust?.rcaReady]);

  async function chooseResolution(option: any) {
    if (selectedAiTrust?.rcaReady !== true) {
      setResolutionStatus("Resolution selection is blocked until backend readiness is verified.");
      return;
    }
    setResolutionStatus("Preparing the selected resolution...");
    setPendingPlanId(option.id);
    try {
      const response: any = await fetchJson("/api-gateway/analysis/resolution-catalog/select", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
        body: JSON.stringify(resolutionSelectionPayload(
          resolutionBinding,
          option,
          selectedRcaDecision?.rootCause,
          resolutionService,
        )),
        timeoutMs: 10000,
      });
      const result = response?.data || response || {};
      const persisted = result?.selected;
      if (!persisted?.plan_id || !persisted?.plan_fingerprint) {
        throw new Error("The backend did not return a persisted governed plan.");
      }
      const refreshed: any = await onRefreshSelectedAlert();
      const refreshedPayload = refreshed?.data || refreshed || {};
      const refreshedWorkflow = refreshedPayload?.workflow || refreshedPayload;
      if (!governedPlanMatchesSelection(refreshedWorkflow, persisted)) {
        throw new Error("Stale selection: the refreshed incident does not reference the selected recommendation and plan. Review the current incident before continuing.");
      }
      setResolutionStatus("Governed plan persisted and verified from the incident projection.");
    } catch (error: any) {
      setResolutionStatus(error?.message || "The resolution plan could not be prepared.");
    } finally {
      setPendingPlanId("");
    }
  }

  async function submitStructuredFeedback() {
    if (!feedbackDraft.decision) return;
    await onSubmitAiRecommendationFeedback(feedbackDraft);
  }

  return (
    <section className="combined-analysis-page context-workspace">
      {selectedAiTrust?.contractValid !== true ? <p className="ai-trust-warning" role="alert"><ShieldAlert size={16} />Investigation contract invalid. Resolution and approval actions are disabled until fresh analysis publishes a valid bound contract.</p> : null}
      {selectedAiTrust?.integrityVerified !== true && selectedAiTrust?.integrity?.status ? <p className="ai-trust-warning" role="alert"><ShieldAlert size={16} />Investigation integrity error: {String(selectedAiTrust.integrity.status).replaceAll("_", " ")}. Resolution is blocked.</p> : null}
      {requiresFreshRecovery ? <section className="context-contract-recovery" aria-label="Recover investigation contract"><div><strong>Fresh context is required</strong><p>KaiMS will collect a new immutable context snapshot and bind the replacement RCA to it.</p></div><button type="button" className="button-primary" disabled={selectedAlertRegeneration.loading} onClick={() => { onSetRcaAnalysisMode("fresh"); return onRerunRca("fresh"); }}><RotateCw size={15} aria-hidden="true" className={selectedAlertRegeneration.loading ? "is-spinning" : ""} />{selectedAlertRegeneration.loading ? "Collecting fresh context…" : "Collect fresh context now"}</button></section> : null}
      <header className="context-workspace-hero">
        <div className="context-workspace-title">
          <span className="discovery-eyebrow">Incident understanding</span>
          <h2>Context and evidence</h2>
          <p>See what is known, what KaiMS inferred, and what still needs operator judgment.</p>
        </div>
        <div className="context-workspace-summary" aria-label="Analysis summary">
          <span className={`context-status is-${reviewRequired ? "review" : "ready"}`}>
            {reviewRequired ? <ShieldAlert size={16} /> : <CheckCircle2 size={16} />}{decisionStatus}
          </span>
          <dl>
            <div><dt>{confidenceLabel}</dt><dd>{formatQualityPercent(confidence)}</dd></div>
            <div><dt>Supporting evidence</dt><dd>{supportingEvidenceRows.length}</dd></div>
            <div><dt>Evidence gaps</dt><dd>{missingEvidence.length}</dd></div>
          </dl>
        </div>
      </header>

      {analysisReused ? <aside className="rca-reuse-banner" role="status"><CheckCircle2 size={18} /><div><strong>Verified analysis reused</strong><span>Scope and freshness checks passed at {formatQualityPercent(analysisReuseScore)} similarity. Refresh if the deployment or symptoms changed.</span></div></aside> : null}

      <DecisionReadinessPanel title="Investigation readiness" checks={investigationChecks} eligibleLabel="Evidence ready for operator review" onReviewEvidence={() => onSetRcaDetailView("evidence")} />

      {resolutionBinding.incident_id ? <ContextEnrichmentPanel
        incidentId={resolutionBinding.incident_id}
        accessToken={accessToken}
        declaredGaps={missingEvidence.map((gap: any) => String(gap?.category || gap))}
        onEvidenceChanged={() => onRerunRca("fresh")}
      /> : null}

      <div className="context-workspace-toolbar">
        <nav className="rca-view-tabs" aria-label="Context workspace views" role="tablist">
          {RCA_VIEWS.map((view) => <button key={view.id} type="button" role="tab" aria-selected={rcaDetailView === view.id} className={rcaDetailView === view.id ? "active" : ""} onClick={() => onSetRcaDetailView(view.id)}><strong>{view.label}{view.id === "evidence" ? ` (${evidenceRows.length})` : ""}</strong><small>{view.description}</small></button>)}
        </nav>
        <details className="context-refresh-control">
          <summary><RotateCw size={15} /> Refresh analysis</summary>
          <div>
            <label htmlFor="rca-analysis-mode">Context strategy</label>
            <select id="rca-analysis-mode" value={rcaAnalysisMode} onChange={(event) => onSetRcaAnalysisMode(event.target.value as "smart" | "fresh" | "cache")} disabled={selectedAlertRegeneration.loading}><option value="smart">Smart reuse</option><option value="fresh">Collect fresh context</option><option value="cache">Verified cache only</option></select>
            <button type="button" className="button-primary" onClick={() => onRerunRca()} disabled={selectedAlertRegeneration.loading}><RotateCw size={15} aria-hidden="true" className={selectedAlertRegeneration.loading ? "is-spinning" : ""} />{selectedAlertRegeneration.loading ? "Analyzing..." : "Run analysis"}</button>
          </div>
        </details>
      </div>

      {rcaDetailView === "simple" ? <section className="decision-command-brief" aria-labelledby="decision-brief-title">
        <div className="decision-command-main">
          <header><div><span className="discovery-eyebrow">Decision brief</span><h3 id="decision-brief-title">Leading explanation</h3></div><span className={`rca-confidence is-${decisionTone}`}><strong>{formatQualityPercent(confidence)}</strong><span>{selectedRcaDecision?.confidenceLabel || "confidence"}</span></span></header>
          <article className="leading-explanation"><span className="explainability-label is-inference">AI inference</span><h4>{selectedRcaDecision?.rootCause || "A probable cause has not been established."}</h4><p>{selectedRcaDecision?.causalDetails || "KaiMS needs more direct evidence before it can explain the causal mechanism."}</p><small>{selectedRcaDecision?.status === "hypothesis" ? "This is a hypothesis, not a confirmed cause." : selectedRcaDecision?.status === "insufficient-evidence" ? "The evidence is insufficient to confirm a cause." : "This explanation is grounded in the currently linked evidence."}</small></article>
          <ol className="decision-process-list" aria-label="Cause to action explanation">
            <li><span>1</span><div><small>Observed impact</small><strong>{selectedRcaDecision?.customerImpact || "Impact not established"}</strong><p>{selectedRcaDecision?.serviceImpact || "No measured service impact was supplied."}</p></div></li>
            <li><span>2</span><div><small>Operational judgment</small><strong>{selectedRcaDecision?.urgency || "Priority requires review"}</strong><p>{selectedRcaDecision?.dependencyImpact || "No dependency impact was supplied."}</p></div></li>
            <li><span>3</span><div><small>Recommended next action</small><strong>{selectedRcaDecision?.action || "Collect more evidence"}</strong><p>{reviewRequired ? "Resolve the evidence gaps, then review the exact target and plan." : "Review the exact target, safeguards, rollback, and recovery checks before execution."}</p></div></li>
          </ol>
        </div>
        <aside className="decision-command-sidebar" aria-label="Decision readiness">
          <div className={`decision-readiness-card is-${reviewRequired ? "review" : "ready"}`} role="status">{reviewRequired ? <ShieldAlert size={22} /> : <CheckCircle2 size={22} />}<div><strong>{decisionStatus}</strong><span>{reviewRequired ? (missingEvidence.length || conflictingEvidence.length ? `${missingEvidence.length} gap(s) and ${conflictingEvidence.length} conflict(s) need attention; ${supportingEvidenceRows.length} observation(s) currently support the RCA.` : "Confidence or grounding requires operator validation.") : `${supportingEvidenceRows.length} evidence record(s) support operator review.`}</span></div></div>
          <div className="decision-confidence-meter"><div><span>{confidenceLabel}</span><strong>{confidencePercent}%</strong></div><div role="progressbar" aria-label={confidenceLabel} aria-valuemin={0} aria-valuemax={100} aria-valuenow={confidencePercent}><span style={{ width: `${confidencePercent}%` }} /></div><p>{selectedAiTrust?.confidenceActionable ? "The RCA is confirmed and still subject to policy gates." : "This is a diagnostic hypothesis score, not a confirmed RCA or execution permission."}</p></div>
          <dl className="decision-context-facts"><div><dt>Signal source</dt><dd>{sourceChannel || "Unknown"}</dd></div><div><dt>Context package</dt><dd>{contextMetadata.context_reused ? "Validated reuse" : "Current incident"}</dd></div><div><dt>Evidence freshness</dt><dd>{freshEvidenceCount} live / {cachedEvidenceCount} cached</dd></div></dl>
          <div className="decision-command-actions"><button type="button" className="button-secondary" onClick={() => onSetRcaDetailView("evidence")}>Inspect evidence</button><button type="button" className="button-primary" disabled={selectedAiTrust?.executionReady !== true} onClick={() => onSetHomeDetailTab("execution")}>{selectedAiTrust?.executionReady === true ? "Review remediation plan" : "Plan blocked by readiness"}</button></div>
        </aside>
        <footer className="explainability-legend" aria-label="Explainability legend"><span><i className="is-observed" />Observed: directly reported by a source</span><span><i className="is-inferred" />Inferred: generated from linked evidence</span><span><i className="is-action" />Action: requires policy and operator gates</span></footer>
      </section> : null}

      {rcaDetailView === "detailed" ? <section className="analysis-workbench" aria-labelledby="analysis-workbench-title">
        <header className="analysis-workbench-header"><div><span className="discovery-eyebrow">Causal analysis</span><h3 id="analysis-workbench-title">Evidence, reasoning, and response options</h3><p>Review the model's reasoning separately from the facts it used.</p></div><button type="button" className="button-primary" onClick={() => onSetHomeDetailTab("execution")}>Continue to remediation</button></header>
        <div className={reviewRequired ? "analysis-alert needs-review" : "analysis-alert is-ready"} role="status">{reviewRequired ? <ShieldAlert size={18} /> : <CheckCircle2 size={18} />}<div><strong>{decisionStatus}</strong><span>{missingEvidence.length ? `Missing evidence: ${missingEvidence.join(", ")}` : "The current evidence package supports a guarded operator decision."}</span></div></div>
        <div className="analysis-card-grid">
          <article className="analysis-card"><span className="explainability-label is-inference">AI inference</span><h4>{selectedRcaDecision?.rootCause || "Cause not established"}</h4><dl><div><dt>Causal mechanism</dt><dd>{selectedRcaDecision?.causalDetails || "Not supplied"}</dd></div><div><dt>Assessment</dt><dd>{selectedRcaDecision?.status === "hypothesis" ? "Hypothesis — not yet confirmed" : selectedRcaDecision?.status === "insufficient-evidence" ? "Insufficient evidence" : "Grounded in linked evidence"}</dd></div><div><dt>Evidence identifiers</dt><dd>{selectedRcaDecision?.rca?.evidence_used?.length ? selectedRcaDecision.rca.evidence_used.join(", ") : "No RCA evidence identifiers supplied"}</dd></div></dl></article>
          <article className="analysis-card"><span className="explainability-label is-observed">Observed and reported</span><h4>{selectedRcaDecision?.customerImpact || "Impact not established"}</h4><dl><div><dt>Service impact</dt><dd>{selectedRcaDecision?.serviceImpact || "Not supplied"}</dd></div><div><dt>Dependency impact</dt><dd>{selectedRcaDecision?.dependencyImpact || "Not supplied"}</dd></div><div><dt>Affected services</dt><dd>{impactedServices.length ? impactedServices.join(", ") : "None identified"}</dd></div><div><dt>Impact evidence</dt><dd>{impactEvidence.length ? impactEvidence.join(", ") : "No impact evidence identifiers supplied"}</dd></div></dl></article>
        </div>
        <section className="reasoning-trace" aria-labelledby="reasoning-trace-title"><header><span className="discovery-eyebrow">Explainability trace</span><h4 id="reasoning-trace-title">How the recommendation was formed</h4></header><ol><li><span>1</span><div><strong>Collect observations</strong><p>{evidenceRows.length ? `${evidenceRows.length} context records were collected; ${freshEvidenceCount} are live and ${supportingEvidenceRows.length} were accepted as RCA support.` : "No linked evidence records are available."}</p></div></li><li><span>2</span><div><strong>Infer the probable cause</strong><p>{selectedRcaDecision?.rootCause || "No probable cause was produced."}</p></div></li><li><span>3</span><div><strong>Propose a guarded response</strong><p>{selectedRcaDecision?.action || "Collect more evidence before acting."}</p></div></li></ol></section>
        <section className="resolution-catalog" aria-labelledby="resolution-catalog-title"><header><div><span className="discovery-eyebrow">Resolution catalog</span><h4 id="resolution-catalog-title">Matched response options</h4><p>Selecting an option persists a governed plan for review; it does not approve or execute it.</p></div><span>{resolutionOptions.length} match{resolutionOptions.length === 1 ? "" : "es"}</span></header><div className="resolution-option-grid">{resolutionOptions.map((option) => <button key={option.id} type="button" disabled={Boolean(pendingPlanId)} className={selectedResolution?.catalog_option_id === option.id ? "selected" : ""} onClick={() => chooseResolution(option)}><span><strong>{option.title}</strong><small>{option.risk} risk</small></span><p>{option.applicability}</p><em>{option.match_reasons?.length ? `Matched: ${option.match_reasons.join(", ")}` : "Diagnostic fallback"}</em></button>)}</div>{!resolutionOptions.length && !resolutionStatus ? <p className="resolution-empty">No catalog match has been returned yet.</p> : null}{resolutionStatus ? <p className="resolution-status" role="status">{resolutionStatus}</p> : null}{selectedResolution ? <div className="resolution-plan"><dl><div><dt>Recommendation / RCA</dt><dd>v{selectedResolution.recommendation_version} / v{selectedResolution.rca_version}</dd></div><div><dt>Plan</dt><dd>{selectedResolution.plan_id} · v{selectedResolution.plan_version}</dd></div><div><dt>Fingerprint</dt><dd><code>{selectedResolution.plan_fingerprint}</code></dd></div><div><dt>Catalog option</dt><dd>{selectedResolution.catalog_option_id} · {selectedResolution.catalog_option_version}</dd></div><div><dt>Context snapshot</dt><dd>{selectedResolution.context_snapshot_id}</dd></div><div><dt>Target / connector</dt><dd>{selectedResolution.target_resource} / {selectedResolution.connector_id}</dd></div><div><dt>Risk</dt><dd>{selectedResolution.risk}</dd></div></dl><div><strong>Validators</strong><ol>{(selectedResolution.validators || []).map((step: string) => <li key={step}>{step}</li>)}</ol></div><div><strong>Rollback</strong><ol>{(selectedResolution.rollback || []).map((step: string) => <li key={step}>{step}</li>)}</ol></div>{selectedResolution.readiness_blocks?.length ? <p className="ai-trust-warning">Readiness blockers: {selectedResolution.readiness_blocks.join(", ")}</p> : null}<button type="button" className="button-primary" onClick={() => onSetHomeDetailTab("execution")}>Review governed plan</button></div> : null}</section>
        {proposedCodeChanges.length ? <details className="rca-code-changes"><summary>Proposed source changes ({proposedCodeChanges.length})</summary>{proposedCodeChanges.map((change: any, index: number) => <article key={`${change.evidence_id || "change"}-${index}`}><div><strong>{change.title || "Proposed change"}</strong><code>{change.source_uri || "Source path unavailable"}</code></div><p>{change.explanation || change.limitations || "Review the cited source evidence before applying this change."}</p>{change.patch ? <pre className="result">{change.patch}</pre> : <p className="status-message">Patch withheld: {change.limitations || "more source context is required."}</p>}</article>)}</details> : null}
        <footer className="rca-analysis-meta"><span>Analysis: <strong>{String(selectedRcaDecision?.status || "unknown").replaceAll("-", " ")}</strong></span><span>Latest evidence: <strong>{evidenceRows[0]?.timestamp ? formatUtcTimestamp(evidenceRows[0].timestamp) : "timestamp not supplied"}</strong></span><span>Grounding: <strong>{formatQualityPercent(Number(selectedAlertEvaluation?.groundingScore || 0))}</strong></span><span>Citations: <strong>{formatQualityPercent(Number(selectedAlertEvaluation?.citationCoverage || 0))}</strong></span></footer>
      </section> : null}

      {rcaDetailView === "evidence" ? <>
        <section className="ai-trust-panel evidence-review" aria-labelledby="ai-trust-title">
          <header className="evidence-review-header"><div><span className="discovery-eyebrow">Evidence review</span><h3 id="ai-trust-title">What the analysis is grounded on</h3><p>Verify provenance, freshness, and gaps before relying on the inferred cause.</p></div><div className={`evidence-confidence is-${qualityToneFromScore(confidence)}`}><Sparkles size={18} /><span><strong>{formatQualityPercent(confidence)}</strong><small>{confidenceLabel}</small></span></div></header>
          <section className="understand-source-matrix" aria-labelledby="evidence-coverage-title"><header><div><Search size={18} /><span><strong id="evidence-coverage-title">Evidence coverage</strong><small>Only sources represented in the backend evidence contract are marked available.</small></span></div><b>{connectedEvidenceSources}/{evidenceSources.length} categories represented</b></header><div>{evidenceSources.map(({ id, label, icon: Icon, count, fresh }) => <button type="button" key={id} className={count ? "has-evidence" : "is-missing"} onClick={() => onSetRcaDetailView(count ? "evidence" : "technical")}><i><Icon size={18} /></i><span><strong>{label}</strong><small>{count ? `${count} record${count === 1 ? "" : "s"} · ${fresh} live` : "No linked evidence"}</small></span>{count ? <CheckCircle2 size={16} /> : <ShieldAlert size={16} />}</button>)}</div></section>
          {contextQuality?.contract_version ? <section className={`context-quality-card ${contextQuality.reusable ? "is-reusable" : "needs-refresh"}`} aria-labelledby="context-package-title"><header><div><span className="discovery-eyebrow">Context package</span><strong id="context-package-title">{contextQuality.reusable ? "Context reusable" : "Refresh required"}</strong><small>{contextMetadata.context_reused ? "Reused after scope and freshness validation" : "Collected for this incident"} · reuse quality, not RCA confidence · {contextQuality.contract_version}</small></div><b>{formatQualityPercent(Number(contextQuality.quality_score || 0))}</b></header><dl><div><dt>Evidence-plane coverage</dt><dd>{formatQualityPercent(sourceCoverageScore)}</dd></div><div><dt>RCA readiness</dt><dd>{formatQualityPercent(rcaReadinessScore)}</dd></div><div><dt>Provenance</dt><dd>{formatQualityPercent(Number(contextQuality.provenance_score || 0))}</dd></div><div><dt>Evidence</dt><dd>{Number(contextQuality.evidence_count || 0)} records</dd></div></dl><div className="context-source-statuses">{contextSourceRows.length ? contextSourceRows.map((source) => <span key={source.source} className={`is-${source.status.replaceAll("_", "-")}`}><i aria-hidden="true" /><strong>{source.source}</strong><small>{source.status.replaceAll("_", " ")} · {source.count} records{source.inferredTimestamps ? ` · ${source.inferredTimestamps} inferred timestamps` : ""}</small></span>) : <span className="is-missing"><i aria-hidden="true" /><strong>No source manifest</strong><small>Refresh required</small></span>}</div>{contextQuality.rca_ready !== true || contextQuality.missing_required?.length || contextQuality.stale_sources?.length || inferredContextTimestamps ? <p role="status"><ShieldAlert size={16} />{contextQuality.rca_ready !== true ? `RCA is not ready: ${formatQualityPercent(rcaReadinessScore)} diagnostic readiness. ` : ""}{contextQuality.missing_required?.length ? `Missing: ${contextQuality.missing_required.join(", ")}. ` : ""}{contextQuality.stale_sources?.length ? `Stale: ${contextQuality.stale_sources.join(", ")}. ` : ""}{inferredContextTimestamps ? `${inferredContextTimestamps} record(s) have inferred timestamps.` : ""}</p> : null}</section> : <section className="context-quality-card needs-refresh" aria-label="Context package unavailable"><header><div><span className="discovery-eyebrow">Context package</span><strong>Quality contract unavailable</strong><small>The backend did not return coverage, freshness, provenance, and RCA-readiness scores.</small></div></header></section>}
          <div className="evidence-health-strip" aria-label="Evidence health"><span><i><Database size={17} /></i><strong>{evidenceRows.length}</strong><small>linked records</small></span><span><i><Activity size={17} /></i><strong>{freshEvidenceCount}</strong><small>live observations</small></span><span><i><Clock3 size={17} /></i><strong>{cachedEvidenceCount}</strong><small>cached records</small></span><span className={conflictingEvidence.length ? "has-risk" : "is-clear"}><i><ShieldAlert size={17} /></i><strong>{conflictingEvidence.length}</strong><small>conflicts</small></span><span className={missingEvidence.length ? "has-risk" : "is-clear"}><i><Search size={17} /></i><strong>{missingEvidence.length}</strong><small>evidence gaps</small></span></div>
          <section className="evidence-inference-brief"><div><span className="explainability-label is-inference">AI inference</span><strong>{selectedAiTrust?.analysis?.root_cause || canonicalIncidentAnalysis(selectedAlertWorkflow, selectedAlertRow).rootCause}</strong><p>This conclusion is derived from the ledger below; it is not itself a direct observation.</p></div><button type="button" className="button-secondary" onClick={() => onSetRcaDetailView("detailed")}>Review reasoning</button></section>
          {!evidenceRows.length ? <section className="technical-source-manifest" aria-label="Evidence collection attempts"><strong>Connector collection attempts</strong>{contextSourceRows.length ? contextSourceRows.map((source) => <span key={source.source} className={`is-${source.status.replaceAll("_", "-")}`}><i /><b>{source.source}</b><small>{source.attempted ? `Attempted${source.lastAttempt ? ` ${formatUtcTimestamp(source.lastAttempt)}` : ""}` : "Not attempted"} · {source.status.replaceAll("_", " ")}{source.error ? ` · ${source.error}` : ""}{source.requiredConfiguration ? ` · Required: ${source.requiredConfiguration}` : ""}</small></span>) : <p>No connector attempt manifest was returned.</p>}<button type="button" className="button-secondary" onClick={() => onRefreshSelectedAlert()}>Refresh context</button></section> : null}
          {evidenceRows.some((row: any) => row.cached && row.freshness === "stale") ? <p className="ai-trust-warning" role="status">Cached context may predate the current deployment. Refresh before approving a change.</p> : null}
          <details className="evidence-ledger evidence-ledger-modern" open><summary><div><strong>Evidence ledger</strong><span>{evidenceRows.length} context records; {supportingEvidenceRows.length} accepted as RCA support</span></div><span>Show records</span></summary><div className="table-wrap ai-evidence-table contained-table"><table><thead><tr><th>Source</th><th>Observed</th><th>Freshness</th><th>Citation</th><th>Evidence role</th></tr></thead><tbody>{evidenceRows.length ? evidenceRows.map((row: any) => <tr key={row.id}><td><span className="source-badge">{row.source}</span></td><td>{row.timestamp ? formatUtcTimestamp(row.timestamp) : "Timestamp unavailable"}<small className="table-secondary">{row.age}</small></td><td><span className={`evidence-freshness ${row.cached ? "is-cached" : "is-fresh"}`}>{row.cached ? "Cached" : "Live"}</span><small className="table-secondary">{row.freshness}</small></td><td className="evidence-citation"><code title={row.citation || "Not supplied"}>{row.citation || "Not supplied"}</code></td><td>{row.accepted ? "Supports RCA" : row.cached ? "Historical context only" : "Collected context only"}</td></tr>) : <tr><td colSpan={5}>No linked evidence records. Treat this recommendation as ungrounded and require human review.</td></tr>}</tbody></table></div></details>
          <details className="evidence-model-details"><summary>Model diagnostics and confidence reasons</summary><div className="ai-trust-summary-grid ai-trust-summary-compact"><div><strong>Confidence reasons</strong>{confidenceReasons.length ? <ul>{confidenceReasons.map((reason: string) => <li key={reason}>{reason}</li>)}</ul> : <p>No confidence reasons supplied.</p>}</div><div><strong>Model / provider</strong><p>{selectedAiTrust?.providerRow ? `${selectedAiTrust.providerRow.model} / ${selectedAiTrust.providerRow.provider}` : "Not supplied by the workflow contract"}</p></div><div><strong>Fallback model</strong><p>{selectedAiTrust?.fallbackUsed ? "Used — review required" : "No fallback usage reported"}</p></div><div><strong>Analysis attempt</strong><p>{selectedAlertRegeneration?.message || "Current persisted analysis"}</p></div></div></details>
          <section className="structured-ai-feedback" aria-labelledby="ai-feedback-title">
            <div className="ai-feedback-actions" aria-label="Recommendation feedback"><span id="ai-feedback-title">Was this analysis useful?</span>{["helpful", "incorrect", "incomplete"].map((decision) => <button key={decision} type="button" className={aiFeedbackState?.decision === decision || feedbackDraft.decision === decision ? "button-primary" : "button-secondary"} disabled={aiFeedbackState?.loading || !selectedAlertRecommendationId} onClick={() => decision === "helpful" ? onSubmitAiRecommendationFeedback(decision) : setFeedbackDraft((current) => ({ ...current, decision }))}>{decision[0].toUpperCase() + decision.slice(1)}</button>)}</div>
            {["incorrect", "incomplete"].includes(feedbackDraft.decision) ? <div className="ai-feedback-form">
              <label>Reason category <select value={feedbackDraft.reason_category} onChange={(event) => setFeedbackDraft((current) => ({ ...current, reason_category: event.target.value }))}><option value="">Select a reason</option><option value="wrong_root_cause">Wrong root cause</option><option value="missing_evidence">Missing evidence</option><option value="stale_context">Stale context</option><option value="conflicting_evidence">Conflicting evidence</option><option value="unsafe_action">Unsafe recommended action</option><option value="other">Other</option></select></label>
              <label>Corrected cause <input value={feedbackDraft.corrected_cause} placeholder="Optional operator-corrected cause" onChange={(event) => setFeedbackDraft((current) => ({ ...current, corrected_cause: event.target.value }))} /></label>
              <label>Missing evidence <textarea rows={2} value={feedbackDraft.missing_evidence} placeholder="Optional evidence that should be collected" onChange={(event) => setFeedbackDraft((current) => ({ ...current, missing_evidence: event.target.value }))} /></label>
              <label>Operator comment <textarea rows={2} value={feedbackDraft.comment} placeholder="Optional context for model and runbook improvement" onChange={(event) => setFeedbackDraft((current) => ({ ...current, comment: event.target.value }))} /></label>
              <div className="button-row"><button type="button" className="button-primary" disabled={!feedbackDraft.reason_category || aiFeedbackState?.loading} onClick={submitStructuredFeedback}>{aiFeedbackState?.loading ? "Saving feedback…" : "Submit structured feedback"}</button><button type="button" className="button-secondary" onClick={() => setFeedbackDraft({ decision: "", reason_category: "", corrected_cause: "", missing_evidence: "", comment: "" })}>Cancel</button></div>
            </div> : null}
          </section>
          {aiFeedbackState?.message ? <p className="success">{aiFeedbackState.message}</p> : null}{aiFeedbackState?.error ? <p className="error">{aiFeedbackState.error}</p> : null}
        </section>
        <IntelligenceConnectionView workflow={selectedAlertWorkflow} documents={selectedAlertRagDocuments as any} onDownloadDocument={onDownloadRagDocument} />
        <EvidenceDraftReview alertId={selectedAlertId} />
      </> : null}

      {rcaDetailView === "technical" ? <section className="technical-context-workspace" aria-labelledby="technical-context-title">
        <header><div><span className="discovery-eyebrow">Technical trace</span><h3 id="technical-context-title">Collection and retrieval path</h3><p>Inspect backend-reported sources, discovery queries, document retrieval, and agent handoffs.</p></div><dl><div><dt>Timeline stages</dt><dd>{selectedAlertTimelineRows.length}</dd></div><div><dt>Linked documents</dt><dd>{selectedAlertRagDocuments.length}</dd></div><div><dt>Context quality</dt><dd>{formatQualityPercent(Number(selectedAlertEvaluation?.overallScore || 0))}</dd></div></dl></header>
        <div className="technical-source-manifest" aria-label="Backend source manifest"><strong>Backend-reported sources</strong>{contextSourceRows.length ? contextSourceRows.map((source) => <span key={source.source} className={`is-${source.status.replaceAll("_", "-")}`}><i />{source.source}<small>{source.status.replaceAll("_", " ")} · {source.count} records</small></span>) : <p>No source manifest was returned. The UI will not claim unverified integrations.</p>}</div>
        <details className="investigation-deep-dive" open><summary><span><strong>Discovery and context retrieval</strong><small>Queries, scores, source responses, and raw evidence records</small></span><b>Toggle trace</b></summary><div className="combined-analysis-grid"><article className="combined-analysis-card combined-analysis-discovery"><DiscoveryFlowView workflow={selectedAlertWorkflow} timelineRows={selectedAlertTimelineRows as any} selectedAlert={selectedAlertRow} compact /></article><article className="combined-analysis-card combined-analysis-context"><ContextRetrievalGraph workflow={selectedAlertWorkflow} timelineRows={selectedAlertTimelineRows} documents={selectedAlertRagDocuments} evaluation={selectedAlertEvaluation} documentContract={selectedAlertDocumentContract} onLoadDocumentContent={onLoadRagDocumentContent} onDownloadDocument={onDownloadRagDocument} compact /></article></div></details>
      </section> : null}
    </section>
  );
}
