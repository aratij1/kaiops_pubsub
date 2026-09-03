import { useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  Activity, BookOpen, CheckCircle2, Clock3, Code2, Database, FileSearch,
  GitCommit, Network, RotateCw, Search, ShieldAlert, Sparkles,
} from "lucide-react";
import { ContextRetrievalGraph, DiscoveryFlowView } from "../../components/investigation/InvestigationGraphs";
import { canonicalIncidentAnalysis } from "../../domain/incidentAnalysis";
import { routeJson as fetchJson } from "../../services/routeApi";
import { formatQualityPercent, formatUtcTimestamp, qualityToneFromScore } from "../../utils/presentation";
import { useSession } from "../../app/SessionContext";
import EvidenceDraftReview from "./EvidenceDraftReview";
import DecisionReadinessPanel from "./DecisionReadinessPanel";
import ContextEnrichmentPanel from "../../features/incidents/ContextEnrichmentPanel";
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

export function staleApprovalEvidence(evidenceRows: any[]) {
  return evidenceRows.filter((row: any) => (
    row?.accepted === true
    && row?.cached === true
    && String(row?.freshness || "").toLowerCase() === "stale"
  ));
}

export function humanizeRcaHypothesis(value: unknown) {
  const text = String(value || "").trim();
  if (!text) return "";
  // Some connector/code-search payloads are stored as numbered excerpts
  // (for example `5 | "alert": ...`). Never expose that serialization in a
  // summary card. Retain the authored prefix and the useful description.
  const numberedPayload = text.match(/(?:^|\s)\d+\s*\|\s*"(?:alert|source|name|service|environment|severity|description)"/i);
  if (numberedPayload?.index != null) {
    const prefix = text.slice(0, numberedPayload.index).trim().replace(/[,:;-]+$/, "");
    const description = text.match(/"description"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"/i)?.[1]
      ?.replaceAll('\\"', '"').trim();
    const customerBoundary = text.match(/Customer and business impact[^.]*\./i)?.[0];
    return [prefix, description, customerBoundary].filter(Boolean).join(". ").replace(/\.\s*\./g, ".");
  }
  const firstBrace = text.indexOf("{");
  const lastBrace = text.lastIndexOf("}");
  if (firstBrace < 0 || lastBrace <= firstBrace) return text;
  try {
    const payload = JSON.parse(text.slice(firstBrace, lastBrace + 1));
    const summary = [payload.summary, payload.message, payload.description, payload.observation, payload.finding]
      .find((item) => typeof item === "string" && item.trim());
    if (summary) return `${text.slice(0, firstBrace).trim()} ${summary.trim()}`.trim();
    if (payload.query && Array.isArray(payload.series)) {
      return `${text.slice(0, firstBrace).trim()} Prometheus returned ${payload.series.length} time series for query: ${String(payload.query).slice(0, 320)}`.trim();
    }
    const source = payload?.provenance?.source || payload.source || "Connector";
    const status = String(payload.source_status || payload.status || "recorded").replaceAll("_", " ");
    return `${text.slice(0, firstBrace).trim()} ${source} evidence was ${status}; inspect the cited evidence record for details.`.trim();
  } catch {
    const query = text.match(/\\?"query\\?"\s*:\s*\\?"([^"\\]*(?:\\.[^"\\]*)*)/i)?.[1];
    if (query && text.includes("series")) {
      return `${text.slice(0, firstBrace).trim()} Prometheus observed matching time series for query: ${query.replaceAll('\\\\"', '"').slice(0, 320)}`.trim();
    }
    return `${text.slice(0, firstBrace).trim()} Structured evidence is available in the cited record.`.trim();
  }
}

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
  const { accessToken } = useSession();
  const integrityStatus = String(selectedAiTrust?.integrity?.status || "").trim().toLowerCase();
  const integrityRequiresFreshRecovery = ["context_expired", "missing_snapshot_reference", "snapshot_not_found"].includes(integrityStatus);
  const contractPending = selectedAiTrust?.contractPresent === false
    && ["", "missing_recommendation", "legacy_unbound", "analysis_pending"].includes(integrityStatus);
  const contractMalformed = selectedAiTrust?.contractPresent !== false && selectedAiTrust?.contractValid !== true;
  const requiresFreshRecovery = integrityRequiresFreshRecovery;
  const [resolutionOptions, setResolutionOptions] = useState<any[]>([]);
  const [pendingPlanId, setPendingPlanId] = useState("");
  const [resolutionStatus, setResolutionStatus] = useState("");
  const [resolutionReloadToken, setResolutionReloadToken] = useState(0);
  const [canonicalWorkspace, setCanonicalWorkspace] = useState<any>(null);
  const [canonicalEvidenceReadModel, setCanonicalEvidenceReadModel] = useState<any>(null);
  const [workspaceError, setWorkspaceError] = useState("");
  const [reviewEvidenceRequest, setReviewEvidenceRequest] = useState(0);
  const [feedbackDraft, setFeedbackDraft] = useState({ decision: "", reason_category: "", corrected_cause: "", missing_evidence: "", comment: "" });
  const [evidenceQuery, setEvidenceQuery] = useState("");
  const deferredEvidenceQuery = useDeferredValue(evidenceQuery.trim().toLowerCase());
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
  const collectedObservationRows = Object.entries(contextMetadata?.context_evidence || {}).flatMap(
    ([category, rows]: [string, any]) => Array.isArray(rows) ? rows.map((row: any) => ({
      ...row,
      category,
      summary: String(row?.summary || row?.snippet || row?.matched_line || row?.relevant_content || "").trim(),
      source: String(row?.source || row?.source_id || row?.connector || category),
      timestamp: row?.observed_at || row?.timestamp || row?.collected_at || "",
    })) : [],
  ).filter((row: any) => row.summary);
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
  const filteredEvidenceRows = useMemo(() => deferredEvidenceQuery
    ? evidenceRows.filter((row: any) => [row.source, row.citation, row.id, row.freshness]
      .some((value) => String(value || "").toLowerCase().includes(deferredEvidenceQuery)))
    : evidenceRows, [deferredEvidenceQuery, evidenceRows]);
  const supportingEvidenceRows = evidenceRows.filter((row: any) => row.accepted === true);
  const staleApprovalEvidenceRows = staleApprovalEvidence(evidenceRows);
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
  const investigationSourceAssessments = Object.entries(investigationReport?.source_assessments || {})
    .map(([source, value]: [string, any]) => ({ source, ...(value || {}) }))
    .filter((row: any) => Number(row.retrieved_count || 0) > 0);
  const publishedInvestigationConfidence = investigationReport?.conclusion?.confidence;
  const investigationConfidenceAvailable = publishedInvestigationConfidence !== null
    && publishedInvestigationConfidence !== undefined
    && Number.isFinite(Number(publishedInvestigationConfidence));
  const investigationConfidence = investigationConfidenceAvailable
    ? Number(publishedInvestigationConfidence)
    : null;
  const investigationConclusive = investigationReport?.conclusive === true
    && String(investigationReport?.status || "").toLowerCase() === "conclusive";
  const canonicalGroundingScore = Array.isArray(canonicalEvidenceReadModel?.scores)
    ? canonicalEvidenceReadModel.scores.find((score: any) => score?.key === "grounding_coverage")
    : null;
  const groundingScoreAvailable = canonicalGroundingScore?.status === "available"
    && Number.isFinite(Number(canonicalGroundingScore?.percent));
  const groundingScore: number | null = groundingScoreAvailable
    ? Number(canonicalGroundingScore.percent) / 100
    : canonicalEvidenceReadModel
      ? null
      : Number.isFinite(Number(selectedAlertEvaluation?.groundingScore))
        ? Number(selectedAlertEvaluation.groundingScore)
        : null;
  const confidence = Number(selectedAiTrust?.confidence || 0);
  const confidenceLabel = String(selectedAiTrust?.confidenceLabel || "Leading hypothesis confidence");
  const reviewRequired = Boolean(
    selectedRcaDecision?.reviewRequired
    || missingEvidence.length
    || conflictingEvidence.length
    || evidenceRows.length === 0
    || selectedAiTrust?.integrityVerified !== true
    || !investigationConclusive
    || investigationConfidence === null
    || investigationConfidence < 0.65
    || groundingScore === null
    || groundingScore < 0.85
  );
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
  const canonicalEvidenceSummary = canonicalWorkspace?.evidence_summary || {};
  const linkedEvidenceCount = Number(canonicalEvidenceSummary.bound_snapshot_records ?? evidenceRows.length);
  const rcaReferencedEvidenceCount = Number(canonicalEvidenceSummary.rca_bound_records ?? supportingEvidenceRows.length);
  const citationCount = Number(canonicalEvidenceSummary.traceable_citations
    ?? evidenceRows.filter((row: any) => row.accepted === true && String(row.citation || "").trim()).length);
  const investigationChecks = [
    { id: "evidence", label: "Bound observations", detail: linkedEvidenceCount ? `${linkedEvidenceCount} record(s) are frozen in the RCA snapshot; ${rcaReferencedEvidenceCount} are referenced by the analysis.` : "No observations are bound to this RCA snapshot.", passed: linkedEvidenceCount > 0, action: "collect metrics, logs, traces, or change evidence" },
    { id: "citations", label: "Traceable RCA citations", detail: citationCount ? `${citationCount} RCA-referenced record(s) have a verifiable citation.` : "No RCA-referenced records have a verifiable citation.", passed: citationCount > 0, action: "attach source citations" },
    { id: "freshness", label: "Current evidence", detail: freshEvidenceCount ? `${freshEvidenceCount} live record(s) are available.` : "All evidence is cached or freshness is unknown.", passed: freshEvidenceCount > 0, action: "refresh incident context" },
    { id: "conflicts", label: "Conflicts resolved", detail: conflictingEvidence.length ? `${conflictingEvidence.length} conflict(s) require operator review.` : "No conflicting evidence was declared.", passed: conflictingEvidence.length === 0, action: "resolve conflicting observations" },
    { id: "gaps", label: "Declared gaps addressed", detail: missingEvidence.length ? missingEvidence.join(", ") : "The analysis declares no missing evidence.", passed: missingEvidence.length === 0, action: "collect the declared missing evidence" },
    { id: "investigation", label: "Iterative investigation", detail: investigationConclusive ? "The bounded investigation reached a corroborated conclusion." : "The investigation is missing or inconclusive.", passed: investigationConclusive, action: "continue the read-only investigation" },
    { id: "confidence", label: "Evidence confidence", detail: investigationConfidence === null ? "Investigation confidence was not published." : `${formatQualityPercent(investigationConfidence)} investigation confidence.`, passed: investigationConfidence !== null && investigationConfidence >= 0.65, action: "publish corroborated evidence-derived confidence of at least 65%" },
    { id: "grounding", label: "Grounding coverage", detail: groundingScore === null ? "Grounding coverage is unavailable from the canonical evidence read model." : `${formatQualityPercent(groundingScore)} grounding coverage.`, passed: groundingScore !== null && groundingScore >= 0.85, action: "raise grounding coverage to at least 85%" },
  ];

  useEffect(() => {
    const incidentId = resolutionBinding.incident_id;
    if (!incidentId || !accessToken) {
      setCanonicalWorkspace(null);
      setCanonicalEvidenceReadModel(null);
      return undefined;
    }
    const controller = new AbortController();
    fetchJson(`/api-gateway/incidents/${encodeURIComponent(incidentId)}/command`, {
      headers: { Authorization: `Bearer ${accessToken}` }, signal: controller.signal,
      maxAttempts: 1, staleTimeMs: 0,
    }).then((response: any) => {
      const payload = response?.data || response || {};
      const operations = payload?.operations || {};
      setCanonicalWorkspace(operations.investigation_workspace || null);
      setCanonicalEvidenceReadModel(payload?.evidence || null);
      setWorkspaceError(operations.investigation_workspace ? "" : "Canonical investigation workspace was not published by this backend release.");
    }).catch((error: any) => {
      if (error?.name !== "AbortError") {
        setCanonicalEvidenceReadModel(null);
        setWorkspaceError("The canonical investigation workspace is temporarily unavailable.");
      }
    });
    return () => controller.abort();
  }, [
    accessToken,
    resolutionBinding.incident_id,
    resolutionBinding.recommendation_id,
    resolutionBinding.context_snapshot_id,
    selectedAlertRecommendationId,
    selectedAlertRegeneration.loading,
  ]);

  useEffect(() => {
    let active = true;
    setPendingPlanId("");
    setResolutionStatus("");
    if (selectedAiTrust?.rcaReady !== true) {
      setResolutionOptions([]);
      setResolutionStatus("No governed remediation can be matched yet. Close the evidence gaps and rerun RCA first.");
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
    }).catch((error: any) => {
      if (active) setResolutionStatus(error?.message || "Resolution options are temporarily unavailable.");
    });
    return () => { active = false; };
  }, [accessToken, selectedAlertId, selectedRcaDecision?.rootCause, selectedRcaDecision?.action, resolutionBinding, resolutionService, selectedAiTrust?.rcaReady, resolutionReloadToken]);

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
      {contractMalformed && !integrityRequiresFreshRecovery ? <p className="ai-trust-warning" role="alert"><ShieldAlert size={16} />{selectedAiTrust?.contractError || "Investigation contract is malformed"}. Resolution and approval actions remain disabled until analysis publishes a valid bound contract.</p> : null}
      {!contractPending && selectedAiTrust?.integrityVerified !== true && selectedAiTrust?.integrity?.status && !integrityRequiresFreshRecovery ? <p className="ai-trust-warning" role="alert"><ShieldAlert size={16} />Investigation integrity error: {String(selectedAiTrust.integrity.status).replaceAll("_", " ")}. Resolution is blocked.</p> : null}
      {requiresFreshRecovery ? <section className="context-contract-recovery" aria-label="Recover investigation contract"><div><strong>Fresh context is required</strong><p>KaiMS will collect a new immutable context snapshot and bind the replacement RCA to it.</p></div><button type="button" className="button-primary" disabled={selectedAlertRegeneration.loading} onClick={() => { onSetRcaAnalysisMode("fresh"); return onRerunRca("fresh"); }}><RotateCw size={15} aria-hidden="true" className={selectedAlertRegeneration.loading ? "is-spinning" : ""} />{selectedAlertRegeneration.loading ? "Collecting fresh context…" : "Collect fresh context now"}</button></section> : null}
      {canonicalWorkspace ? <header className="context-workspace-hero canonical-investigation-hero">
        <div className="context-workspace-title"><span className="discovery-eyebrow">Governed full investigation</span><h2>{canonicalWorkspace.rca?.status === "grounded" ? "Grounded RCA workspace" : "Evidence review required"}</h2><p>{canonicalWorkspace.operator_review?.message}</p><small>Snapshot v{canonicalWorkspace.binding?.snapshot_version || 0} · RCA v{canonicalWorkspace.binding?.rca_version || 0} · {canonicalWorkspace.binding?.snapshot_id || "snapshot unavailable"}</small></div>
        <div className="canonical-investigation-gates"><article><span>Impact</span><strong>{["observed", "grounded", "established"].includes(String(canonicalWorkspace.impact?.status || "").toLowerCase()) ? (String(canonicalWorkspace.impact?.status).toLowerCase() === "observed" ? "Observed" : "Established") : "Not established"}</strong><p>{humanizeRcaHypothesis(canonicalWorkspace.impact?.statement) || "No accepted evidence establishes customer or business impact."}</p></article><article><span>Root cause</span><strong>{String(canonicalWorkspace.rca?.status || "not started").replaceAll("_", " ")}</strong><p>{humanizeRcaHypothesis(canonicalWorkspace.rca?.hypothesis) || "No falsifiable hypothesis has been published."}</p></article><article><span>Resolution</span><strong>{canonicalWorkspace.resolution?.status || "blocked"}</strong><p>{canonicalWorkspace.resolution?.status === "ready" ? "A governed plan is bound to this RCA." : (canonicalWorkspace.resolution?.blocking_reasons || []).join(", ") || "Grounded RCA required."}</p></article></div>
        <div className="canonical-investigation-ledger"><span><strong>{canonicalWorkspace.evidence_summary?.latest_context_records ?? 0}</strong> latest context records</span><span><strong>{canonicalWorkspace.evidence_summary?.bound_snapshot_records ?? canonicalWorkspace.evidence?.length ?? 0}</strong> records frozen for this RCA</span><span><strong>{canonicalWorkspace.evidence_summary?.rca_bound_records ?? canonicalWorkspace.rca?.resolved_evidence_ids?.length ?? 0}</strong> RCA-bound records</span><span><strong>{canonicalWorkspace.evidence_summary?.traceable_citations ?? canonicalWorkspace.rca?.traceable_citation_count ?? 0}</strong> traceable citations</span></div>
      </header> : <header className="context-workspace-hero">
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
      </header>}
      {workspaceError ? <p className="ai-trust-warning" role="status"><ShieldAlert size={16} />{workspaceError}</p> : null}

      {analysisReused ? <aside className="rca-reuse-banner" role="status"><CheckCircle2 size={18} /><div><strong>Verified analysis reused</strong><span>Scope and freshness checks passed at {formatQualityPercent(analysisReuseScore)} similarity. Refresh if the deployment or symptoms changed.</span></div></aside> : null}

      <section className="investigation-scoreboard" aria-label="Investigation scores and evidence summary">
        <article><span>Context quality</span><strong>{formatQualityPercent(Number(contextQuality.quality_score || 0))}</strong><small>Collection quality</small></article>
        <article><span>RCA readiness</span><strong>{formatQualityPercent(rcaReadinessScore)}</strong><small>Diagnostic readiness</small></article>
        <article><span>Grounding</span><strong>{groundingScore === null ? "Unavailable" : formatQualityPercent(groundingScore)}</strong><small>Traceable RCA coverage</small></article>
        <article><span>RCA citations</span><strong>{citationCount}</strong><small>Traceable references</small></article>
        <article><span>Open gaps</span><strong>{missingEvidence.length}</strong><small>{conflictingEvidence.length} conflict{conflictingEvidence.length === 1 ? "" : "s"}</small></article>
      </section>

      <nav className="investigation-view-tabs" aria-label="Investigation views" role="tablist">
        {([
          ["simple", "Summary", "Decision and next step"],
          ["evidence", "Evidence", "Records and provenance"],
          ["detailed", "Analysis", "Reasoning and options"],
          ["technical", "Technical trace", "Queries and handoffs"],
        ] as const).map(([view, label, description]) => <button key={view} type="button" role="tab" aria-selected={rcaDetailView === view} className={rcaDetailView === view ? "is-active" : ""} onClick={() => onSetRcaDetailView(view)}><strong>{label}</strong><small>{description}</small></button>)}
      </nav>

      {rcaDetailView === "simple" ? <details className="investigation-section investigation-attention" open={reviewRequired}>
        <summary><span><strong>What needs attention</strong><small>{reviewRequired ? `${investigationChecks.filter((check) => !check.passed).length} investigation checks need work` : "All investigation checks passed"}</small></span><b>Show or hide</b></summary>
        <div className="investigation-section-body"><DecisionReadinessPanel title="Investigation readiness" checks={investigationChecks} eligibleLabel="Evidence ready for operator review" onReviewEvidence={() => { onSetRcaAnalysisMode("fresh"); void onRerunRca("fresh"); setReviewEvidenceRequest((value) => value + 1); }} />

      {resolutionBinding.incident_id ? <ContextEnrichmentPanel
        incidentId={resolutionBinding.incident_id}
        alertId={resolutionBinding.alert_id}
        accessToken={accessToken}
        declaredGaps={missingEvidence.map((gap: any) => ({ category: String(gap?.category || gap), reason: String(gap?.reason || "") }))}
        proposedRcaDraft={canonicalWorkspace?.rca?.hypothesis || selectedRcaDecision?.rootCause || ""}
        reviewRequestToken={reviewEvidenceRequest}
        onIncidentRefresh={onRefreshSelectedAlert}
      /> : null}</div></details> : null}

      <div className="context-workspace-toolbar">
        <details className="context-refresh-control">
          <summary><RotateCw size={15} /> Refresh analysis</summary>
          <div>
            <label htmlFor="rca-analysis-mode">Context strategy</label>
            <select id="rca-analysis-mode" value={rcaAnalysisMode} onChange={(event) => onSetRcaAnalysisMode(event.target.value as "smart" | "fresh" | "cache")} disabled={selectedAlertRegeneration.loading}><option value="smart">Smart reuse</option><option value="fresh">Collect fresh context</option><option value="cache">Verified cache only</option></select>
            <button type="button" className="button-primary" onClick={() => onRerunRca()} disabled={selectedAlertRegeneration.loading}><RotateCw size={15} aria-hidden="true" className={selectedAlertRegeneration.loading ? "is-spinning" : ""} />{selectedAlertRegeneration.loading ? "Analyzing..." : "Run analysis"}</button>
          </div>
        </details>
      </div>

      {rcaDetailView === "detailed" ? <details className="investigation-section investigation-analysis" open>
        <summary><span><strong>Cause, impact, and next action</strong><small>Separate observed facts from AI inference and response options</small></span><b>Show or hide</b></summary>
      <section className="analysis-workbench" aria-labelledby="analysis-workbench-title">
        <header className="analysis-workbench-header"><div><span className="discovery-eyebrow">Causal analysis</span><h3 id="analysis-workbench-title">Evidence, reasoning, and response options</h3><p>Review the model's reasoning separately from the facts it used.</p></div><button type="button" className="button-primary" disabled={selectedAiTrust?.rcaReady !== true} onClick={() => onSetHomeDetailTab("execution")}>{selectedAiTrust?.rcaReady === true ? "Continue to remediation" : "Remediation unavailable"}</button></header>
        <div className={reviewRequired ? "analysis-alert needs-review" : "analysis-alert is-ready"} role="status">{reviewRequired ? <ShieldAlert size={18} /> : <CheckCircle2 size={18} />}<div><strong>{decisionStatus}</strong><span>{missingEvidence.length ? `Missing evidence: ${missingEvidence.join(", ")}` : "The current evidence package supports a guarded operator decision."}</span></div></div>
        <div className="analysis-card-grid">
          <article className="analysis-card"><span className="explainability-label is-inference">AI inference</span><h4>{selectedRcaDecision?.rootCause || "Cause not established"}</h4><dl><div><dt>Causal mechanism</dt><dd>{selectedRcaDecision?.causalDetails || "Not supplied"}</dd></div><div><dt>Assessment</dt><dd>{selectedRcaDecision?.status === "hypothesis" ? "Hypothesis — not yet confirmed" : selectedRcaDecision?.status === "insufficient-evidence" ? "Insufficient evidence" : "Grounded in linked evidence"}</dd></div><div><dt>Evidence identifiers</dt><dd>{selectedRcaDecision?.rca?.evidence_used?.length ? selectedRcaDecision.rca.evidence_used.join(", ") : "No RCA evidence identifiers supplied"}</dd></div></dl></article>
          <article className="analysis-card"><span className="explainability-label is-observed">Observed and reported</span><h4>{selectedRcaDecision?.customerImpact || "Impact not established"}</h4><dl><div><dt>Service impact</dt><dd>{selectedRcaDecision?.serviceImpact || "Not supplied"}</dd></div><div><dt>Dependency impact</dt><dd>{selectedRcaDecision?.dependencyImpact || "Not supplied"}</dd></div><div><dt>Affected services</dt><dd>{impactedServices.length ? impactedServices.join(", ") : "None identified"}</dd></div><div><dt>Impact evidence</dt><dd>{impactEvidence.length ? impactEvidence.join(", ") : "No impact evidence identifiers supplied"}</dd></div></dl></article>
        </div>
        <section className="resolution-catalog" aria-labelledby="resolution-catalog-title"><header><div><span className="discovery-eyebrow">Resolution catalog</span><h4 id="resolution-catalog-title">Matched response options</h4><p>Selecting an option persists a governed plan for review; it does not approve or execute it.</p></div><span>{resolutionOptions.length} match{resolutionOptions.length === 1 ? "" : "es"}</span></header><div className="resolution-option-grid">{resolutionOptions.map((option) => <button key={option.id} type="button" disabled={Boolean(pendingPlanId)} className={selectedResolution?.catalog_option_id === option.id ? "selected" : ""} onClick={() => chooseResolution(option)}><span><strong>{option.title}</strong><small>{option.risk} risk</small></span><p>{option.applicability}</p><em>{option.match_reasons?.length ? `Matched: ${option.match_reasons.join(", ")}` : "Diagnostic fallback"}</em></button>)}</div>{!resolutionOptions.length && !resolutionStatus ? <p className="resolution-empty">No governed catalog match was found for this RCA.</p> : null}{resolutionStatus ? <div className="resolution-status" role="status"><p>{resolutionStatus}</p>{selectedAiTrust?.rcaReady === true ? <button type="button" className="button-secondary" onClick={() => setResolutionReloadToken((value) => value + 1)}>Retry catalog</button> : <button type="button" className="button-secondary" onClick={() => { onSetRcaDetailView("simple"); setReviewEvidenceRequest((value) => value + 1); }}>Review missing evidence</button>}</div> : null}{selectedResolution ? <div className="resolution-plan"><dl><div><dt>Recommendation / RCA</dt><dd>v{selectedResolution.recommendation_version} / v{selectedResolution.rca_version}</dd></div><div><dt>Plan</dt><dd>{selectedResolution.plan_id} · v{selectedResolution.plan_version}</dd></div><div><dt>Fingerprint</dt><dd><code>{selectedResolution.plan_fingerprint}</code></dd></div><div><dt>Catalog option</dt><dd>{selectedResolution.catalog_option_id} · {selectedResolution.catalog_option_version}</dd></div><div><dt>Context snapshot</dt><dd>{selectedResolution.context_snapshot_id}</dd></div><div><dt>Target / connector</dt><dd>{selectedResolution.target_resource} / {selectedResolution.connector_id}</dd></div><div><dt>Risk</dt><dd>{selectedResolution.risk}</dd></div></dl><div><strong>Validators</strong><ol>{(selectedResolution.validators || []).map((step: string) => <li key={step}>{step}</li>)}</ol></div><div><strong>Rollback</strong><ol>{(selectedResolution.rollback || []).map((step: string) => <li key={step}>{step}</li>)}</ol></div>{selectedResolution.readiness_blocks?.length ? <p className="ai-trust-warning">Readiness blockers: {selectedResolution.readiness_blocks.join(", ")}</p> : null}<button type="button" className="button-primary" onClick={() => onSetHomeDetailTab("execution")}>Review governed plan</button></div> : null}</section>
        {proposedCodeChanges.length ? <details className="rca-code-changes"><summary>Proposed source changes ({proposedCodeChanges.length})</summary>{proposedCodeChanges.map((change: any, index: number) => <article key={`${change.evidence_id || "change"}-${index}`}><div><strong>{change.title || "Proposed change"}</strong><code>{change.source_uri || "Source path unavailable"}</code></div><p>{change.explanation || change.limitations || "Review the cited source evidence before applying this change."}</p>{change.patch ? <pre className="result">{change.patch}</pre> : <p className="status-message">Patch withheld: {change.limitations || "more source context is required."}</p>}</article>)}</details> : null}
        <footer className="rca-analysis-meta"><span>Analysis: <strong>{String(selectedRcaDecision?.status || "unknown").replaceAll("-", " ")}</strong></span><span>Latest evidence: <strong>{evidenceRows[0]?.timestamp ? formatUtcTimestamp(evidenceRows[0].timestamp) : "timestamp not supplied"}</strong></span><span>Grounding: <strong>{groundingScore === null ? "Unavailable" : formatQualityPercent(groundingScore)}</strong></span><span>Citations: <strong>{citationCount}</strong></span></footer>
      </section></details> : null}

      {rcaDetailView === "evidence" ? <details className="investigation-section investigation-evidence" open>
        <summary><span><strong>Evidence and provenance</strong><small>{evidenceRows.length} records · {supportingEvidenceRows.length} accepted · {freshEvidenceCount} live</small></span><b>Show or hide</b></summary><div className="investigation-section-body">
        <section className="ai-trust-panel evidence-review" aria-labelledby="ai-trust-title">
          <header className="evidence-review-header"><div><span className="discovery-eyebrow">Evidence review</span><h3 id="ai-trust-title">What the analysis is grounded on</h3><p>Verify provenance, freshness, and gaps before relying on the inferred cause.</p></div><div className={`evidence-confidence is-${qualityToneFromScore(confidence)}`}><Sparkles size={18} /><span><strong>{formatQualityPercent(confidence)}</strong><small>{confidenceLabel}</small></span></div></header>
          <section className="understand-source-matrix" aria-labelledby="evidence-coverage-title"><header><div><Search size={18} /><span><strong id="evidence-coverage-title">Evidence coverage</strong><small>Only sources represented in the backend evidence contract are marked available.</small></span></div><b>{connectedEvidenceSources}/{evidenceSources.length} categories represented</b></header><div>{evidenceSources.map(({ id, label, icon: Icon, count, fresh }) => <button type="button" key={id} className={count ? "has-evidence" : "is-missing"} onClick={() => onSetRcaDetailView(count ? "evidence" : "technical")}><i><Icon size={18} /></i><span><strong>{label}</strong><small>{count ? `${count} record${count === 1 ? "" : "s"} · ${fresh} live` : "No linked evidence"}</small></span>{count ? <CheckCircle2 size={16} /> : <ShieldAlert size={16} />}</button>)}</div></section>
          {contextQuality?.contract_version ? <section className={`context-quality-card ${contextQuality.reusable ? "is-reusable" : "needs-refresh"}`} aria-labelledby="context-package-title"><header><div><span className="discovery-eyebrow">Context package</span><strong id="context-package-title">{contextQuality.reusable ? "Context reusable" : "Refresh required"}</strong><small>{contextMetadata.context_reused ? "Reused after scope and freshness validation" : "Collected for this incident"} · reuse quality, not RCA confidence · {contextQuality.contract_version}</small></div><b>{formatQualityPercent(Number(contextQuality.quality_score || 0))}</b></header><dl><div><dt>Evidence-plane coverage</dt><dd>{formatQualityPercent(sourceCoverageScore)}</dd></div><div><dt>RCA readiness</dt><dd>{formatQualityPercent(rcaReadinessScore)}</dd></div><div><dt>Provenance</dt><dd>{formatQualityPercent(Number(contextQuality.provenance_score || 0))}</dd></div><div><dt>Evidence</dt><dd>{Number(contextQuality.evidence_count || 0)} records</dd></div></dl><div className="context-source-statuses">{contextSourceRows.length ? contextSourceRows.map((source) => <span key={source.source} className={`is-${source.status.replaceAll("_", "-")}`}><i aria-hidden="true" /><strong>{source.source}</strong><small>{source.status.replaceAll("_", " ")} · {source.count} records{source.inferredTimestamps ? ` · ${source.inferredTimestamps} inferred timestamps` : ""}</small></span>) : <span className="is-missing"><i aria-hidden="true" /><strong>No source manifest</strong><small>Refresh required</small></span>}</div>{contextQuality.rca_ready !== true || contextQuality.missing_required?.length || contextQuality.stale_sources?.length || inferredContextTimestamps ? <p role="status"><ShieldAlert size={16} />{contextQuality.rca_ready !== true ? `RCA is not ready: ${formatQualityPercent(rcaReadinessScore)} diagnostic readiness. ` : ""}{contextQuality.missing_required?.length ? `Missing: ${contextQuality.missing_required.join(", ")}. ` : ""}{contextQuality.stale_sources?.length ? `Stale: ${contextQuality.stale_sources.join(", ")}. ` : ""}{inferredContextTimestamps ? `${inferredContextTimestamps} record(s) have inferred timestamps.` : ""}</p> : null}</section> : <section className="context-quality-card needs-refresh" aria-label="Context package unavailable"><header><div><span className="discovery-eyebrow">Context package</span><strong>Quality contract unavailable</strong><small>The backend did not return coverage, freshness, provenance, and RCA-readiness scores.</small></div></header></section>}
          {collectedObservationRows.length ? <section className="collected-observations" aria-labelledby="collected-observations-title"><header><div><span className="discovery-eyebrow">Available details</span><strong id="collected-observations-title">What the connectors observed</strong><small>Collected facts are shown even when they do not prove a root cause.</small></div><b>{collectedObservationRows.length} observations</b></header><ul>{collectedObservationRows.slice(0, 8).map((row: any, index: number) => <li key={row.evidence_id || `${row.category}-${index}`}><div><strong>{row.source.replaceAll("_", " ")}</strong><small>{row.timestamp ? formatUtcTimestamp(row.timestamp) : "Observation time unavailable"}</small></div><p>{row.summary}</p></li>)}</ul></section> : null}
          <div className="evidence-health-strip" aria-label="Evidence health"><span><i><Database size={17} /></i><strong>{evidenceRows.length}</strong><small>linked records</small></span><span><i><Activity size={17} /></i><strong>{freshEvidenceCount}</strong><small>live observations</small></span><span><i><Clock3 size={17} /></i><strong>{cachedEvidenceCount}</strong><small>cached records</small></span><span className={conflictingEvidence.length ? "has-risk" : "is-clear"}><i><ShieldAlert size={17} /></i><strong>{conflictingEvidence.length}</strong><small>conflicts</small></span><span className={missingEvidence.length ? "has-risk" : "is-clear"}><i><Search size={17} /></i><strong>{missingEvidence.length}</strong><small>evidence gaps</small></span></div>
          <section className="evidence-inference-brief"><div><span className="explainability-label is-inference">AI inference</span><strong>{selectedAiTrust?.analysis?.root_cause || canonicalIncidentAnalysis(selectedAlertWorkflow, selectedAlertRow).rootCause}</strong><p>This conclusion is derived from the ledger below; it is not itself a direct observation.</p></div><button type="button" className="button-secondary" onClick={() => onSetRcaDetailView("detailed")}>Review reasoning</button></section>
          {!evidenceRows.length ? <section className="technical-source-manifest" aria-label="Evidence collection attempts"><strong>Connector collection attempts</strong>{contextSourceRows.length ? contextSourceRows.map((source) => <span key={source.source} className={`is-${source.status.replaceAll("_", "-")}`}><i /><b>{source.source}</b><small>{source.attempted ? `Attempted${source.lastAttempt ? ` ${formatUtcTimestamp(source.lastAttempt)}` : ""}` : "Not attempted"} · {source.status.replaceAll("_", " ")}{source.error ? ` · ${source.error}` : ""}{source.requiredConfiguration ? ` · Required: ${source.requiredConfiguration}` : ""}</small></span>) : <p>No connector attempt manifest was returned.</p>}<button type="button" className="button-secondary" onClick={() => onRefreshSelectedAlert()}>Refresh context</button></section> : null}
          {staleApprovalEvidenceRows.length ? <p className="ai-trust-warning stale-evidence-warning" role="alert"><span>{staleApprovalEvidenceRows.length} RCA-bound evidence record{staleApprovalEvidenceRows.length === 1 ? " is" : "s are"} stale. Collect fresh context before approval.</span><button type="button" className="button-secondary" disabled={selectedAlertRegeneration.loading} onClick={() => { onSetRcaAnalysisMode("fresh"); return onRerunRca("fresh"); }}>{selectedAlertRegeneration.loading ? "Collecting…" : "Collect fresh context"}</button></p> : null}
          <details className="evidence-ledger evidence-ledger-modern"><summary><div><strong>Evidence ledger</strong><span>{evidenceRows.length} context records; {supportingEvidenceRows.length} accepted as RCA support</span></div><span>Review records</span></summary><div className="evidence-ledger-tools"><label htmlFor="evidence-ledger-search">Find evidence</label><div><Search size={16} aria-hidden="true" /><input id="evidence-ledger-search" type="search" value={evidenceQuery} onChange={(event) => setEvidenceQuery(event.target.value)} placeholder="Source, citation, ID, or freshness" /></div><small>{filteredEvidenceRows.length} of {evidenceRows.length} records</small></div><div className="table-wrap ai-evidence-table contained-table"><table><thead><tr><th>Source</th><th>Observed</th><th>Freshness</th><th>Citation</th><th>Evidence role</th></tr></thead><tbody>{filteredEvidenceRows.length ? filteredEvidenceRows.map((row: any) => <tr key={row.id}><td><span className="source-badge">{row.source}</span></td><td>{row.timestamp ? formatUtcTimestamp(row.timestamp) : "Timestamp unavailable"}<small className="table-secondary">{row.age}</small></td><td><span className={`evidence-freshness ${row.cached ? "is-cached" : "is-fresh"}`}>{row.cached ? "Cached" : "Live"}</span><small className="table-secondary">{row.freshness}</small></td><td className="evidence-citation"><code title={row.citation || "Not supplied"}>{row.citation || "Not supplied"}</code></td><td>{row.accepted ? "Supports RCA" : row.cached ? "Historical context only" : "Collected context only"}</td></tr>) : <tr><td colSpan={5}>{evidenceRows.length ? "No evidence matches this search." : "No linked evidence records. Treat this recommendation as ungrounded and require human review."}</td></tr>}</tbody></table></div></details>
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
        <EvidenceDraftReview alertId={selectedAlertId} contextSnapshotId={resolutionBinding.context_snapshot_id} recommendationId={resolutionBinding.recommendation_id} />
      </div></details> : null}

      {rcaDetailView === "technical" ? <details className="advanced-investigation" open>
        <summary><span><strong>Advanced diagnostics</strong><small>Source manifests, collection queries, retrieval scores, and agent handoffs</small></span><b>Open technical trace</b></summary>
      <section className="technical-context-workspace" aria-labelledby="technical-context-title">
        <header><div><span className="discovery-eyebrow">Technical trace</span><h3 id="technical-context-title">Collection and retrieval path</h3><p>Inspect backend-reported sources, discovery queries, document retrieval, and agent handoffs.</p></div><dl><div><dt>Timeline stages</dt><dd>{selectedAlertTimelineRows.length}</dd></div><div><dt>Linked documents</dt><dd>{selectedAlertRagDocuments.length}</dd></div><div><dt>Context quality</dt><dd>{formatQualityPercent(Number(selectedAlertEvaluation?.overallScore || 0))}</dd></div></dl></header>
        <div className="technical-source-manifest" aria-label="Backend source manifest"><strong>Backend-reported sources</strong>{contextSourceRows.length ? contextSourceRows.map((source) => <span key={source.source} className={`is-${source.status.replaceAll("_", "-")}`}><i />{source.source}<small>{source.status.replaceAll("_", " ")} · {source.count} records</small></span>) : <p>No source manifest was returned. The UI will not claim unverified integrations.</p>}</div>
        {investigationSourceAssessments.length ? <div className="technical-source-manifest" aria-label="Investigation source analysis"><strong>How the agent used each source</strong>{investigationSourceAssessments.map((row: any) => <span key={row.source}><i /><b>{row.source}</b><small>{String(row.disposition || "reviewed").replaceAll("_", " ")} · {Number(row.retrieved_count || 0)} reviewed · {Number(row.supporting_count || 0)} used as support</small></span>)}</div> : null}
        <details className="investigation-deep-dive" open><summary><span><strong>Discovery and context retrieval</strong><small>Queries, scores, source responses, and raw evidence records</small></span><b>Toggle trace</b></summary><div className="combined-analysis-grid"><article className="combined-analysis-card combined-analysis-discovery"><DiscoveryFlowView workflow={selectedAlertWorkflow} timelineRows={selectedAlertTimelineRows as any} selectedAlert={selectedAlertRow} compact /></article><article className="combined-analysis-card combined-analysis-context"><ContextRetrievalGraph workflow={selectedAlertWorkflow} timelineRows={selectedAlertTimelineRows} documents={selectedAlertRagDocuments} evaluation={selectedAlertEvaluation} documentContract={selectedAlertDocumentContract} onLoadDocumentContent={onLoadRagDocumentContent} onDownloadDocument={onDownloadRagDocument} compact /></article></div></details>
      </section>
      </details> : null}
    </section>
  );
}
