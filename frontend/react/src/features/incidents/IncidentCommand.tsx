import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  ExternalLink,
  FileCheck2,
  Gauge,
  GitBranch,
  PauseCircle,
  RefreshCw,
  RotateCcw,
  SearchCheck,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";

import { useRouteRuntimeSlice, type ApprovalRow, type IncidentRow } from "../../app/routeRuntime";
import { EmptyState, ErrorState, LoadingState, StatusBadge, TechnicalDetails } from "../../components/design-system";
import { IncidentCommandWorkspaceSchema } from "../../schemas/apiContracts";
import { requestValidated } from "../../services/apiClient";
import ContextEnrichmentPanel, { type EvidenceGap } from "./ContextEnrichmentPanel";

const RELEASE_SHA = String(import.meta.env.VITE_KAIMS_RELEASE_SHA || "dev");
import "./IncidentCommand.css";

type UnknownRecord = Record<string, unknown>;

const TERMINAL = ["closed", "resolved", "recovered", "cancelled"];
const FAILED = ["failed", "rollback_failed", "validation_failed", "manual_intervention_required"];
const JOURNEY = ["Detected", "Understanding", "Root cause", "Resolution", "Executing", "Verifying", "Recovered"] as const;

function record(value: unknown): UnknownRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
}

function firstRecord(...values: unknown[]): UnknownRecord {
  return values.map(record).find((candidate) => Object.keys(candidate).length > 0) || {};
}

function text(...values: unknown[]): string {
  const value = values.find((candidate) => typeof candidate === "string" || typeof candidate === "number");
  return value === undefined || value === null ? "" : String(value).trim();
}

function incidentId(row: IncidentRow) {
  return text(row.incident_id, row.id);
}

function normalizedStatus(row: IncidentRow) {
  return text(row.status, record(row.projection_payload).status, "investigating").toLowerCase();
}

function titleFor(row: IncidentRow) {
  const projection = record(row.projection_payload);
  const eventPayload = record(projection.event_payload);
  const context = firstRecord(row.context, projection.context, eventPayload.context);
  const source = firstRecord(row.source_alert, projection.source_alert, record(context.alert), eventPayload.alert);
  const labels = record(source.labels);
  const annotations = record(source.annotations);
  return text(row.title, row.summary, projection.title, projection.summary, source.title, source.name, labels.alertname, annotations.summary, `${row.service || "Service"} incident`);
}

function dateLabel(value: unknown) {
  const date = new Date(text(value));
  return Number.isFinite(date.getTime()) ? date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "Unavailable";
}

function ageLabel(value: unknown) {
  const date = new Date(text(value));
  if (!Number.isFinite(date.getTime())) return "Freshness unavailable";
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60_000));
  if (minutes < 1) return "less than a minute ago";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}

function confidenceValue(...values: unknown[]) {
  const raw = values.map((value) => Number(value)).find((value) => Number.isFinite(value));
  if (raw === undefined) return null;
  return Math.round(Math.max(0, Math.min(1, raw > 1 ? raw / 100 : raw)) * 100);
}

function arrayOfText(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => text(item)).filter(Boolean);
  const candidate = text(value);
  return candidate ? [candidate] : [];
}

function valueOrUnavailable(value: unknown) {
  if (Array.isArray(value)) {
    const items = value.map((item) => text(item)).filter(Boolean);
    return items.length ? items.join("; ") : "Not provided by backend";
  }
  return text(value) || "Not provided by backend";
}

function StateBadge({ status }: { status: string }) {
  const tone = TERMINAL.some((value) => status.includes(value)) ? "success" : FAILED.some((value) => status.includes(value)) ? "critical" : status.includes("approval") ? "warning" : "info";
  return <StatusBadge tone={tone}>{status.replaceAll("_", " ")}</StatusBadge>;
}

function Metric({ label, value, detail }: { label: string; value: ReactNode; detail?: string }) {
  return <div className="ic-metric"><span>{label}</span><strong>{value}</strong>{detail ? <small>{detail}</small> : null}</div>;
}

export default function IncidentCommand() {
  const routeParams = useParams();
  const routeIncidentId = routeParams.incidentId ?? routeParams["*"] ?? "";
  const navigate = useNavigate();
  const incidents = useRouteRuntimeSlice("incidents");
  const approvals = useRouteRuntimeSlice("approvals");
  const session = useRouteRuntimeSlice("session");
  const [backendReleaseSha, setBackendReleaseSha] = useState("");
  const [approvalExpanded, setApprovalExpanded] = useState(false);
  const [directRequestVersion, setDirectRequestVersion] = useState(0);
  const [directIncident, setDirectIncident] = useState<{
    loading: boolean;
    loaded: boolean;
    row: IncidentRow | null;
    error: string;
  }>({ loading: false, loaded: false, row: null, error: "" });
  const [operationsState, setOperationsState] = useState<UnknownRecord>({});
  const [evidenceReadModel, setEvidenceReadModel] = useState<UnknownRecord>({});
  const [amendmentOpen, setAmendmentOpen] = useState(false);
  const [amendmentStatement, setAmendmentStatement] = useState("");
  const [amendmentReason, setAmendmentReason] = useState("");
  const [amendmentSource, setAmendmentSource] = useState("");
  const [amendmentStatus, setAmendmentStatus] = useState("");
  const [amendmentSubmitting, setAmendmentSubmitting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const loadRelease = async () => {
      try {
        const response = await fetch("/api-gateway/build-info", {
          headers: session.accessToken ? { Authorization: `Bearer ${session.accessToken}`, Accept: "application/json" } : { Accept: "application/json" },
          signal: controller.signal,
        });
        if (!response.ok) return;
        const payload = record(await response.json() as unknown);
        setBackendReleaseSha(text(payload.release_sha));
      } catch (reason) {
        if ((reason as Error)?.name !== "AbortError") setBackendReleaseSha("");
      }
    };
    void loadRelease();
    return () => controller.abort();
  }, [session.accessToken]);

  const requestedIncidentId = useMemo(() => decodeURIComponent(routeIncidentId).trim(), [routeIncidentId]);
  const scopedRow = useMemo(() => incidents.rows.find((candidate) => incidentId(candidate).toLowerCase() === requestedIncidentId.toLowerCase()), [incidents.rows, requestedIncidentId]);
  useEffect(() => {
    if (!requestedIncidentId) {
      setDirectIncident({ loading: false, loaded: true, row: null, error: "" });
      setOperationsState({});
      setEvidenceReadModel({});
      return undefined;
    }
    const controller = new AbortController();
    const loadRequestedIncident = async () => {
      setDirectIncident((current) => ({ ...current, loading: true, loaded: false, error: "" }));
      try {
        const workspace = await requestValidated(
          `/api-gateway/incidents/${encodeURIComponent(requestedIncidentId)}/command`,
          IncidentCommandWorkspaceSchema,
          {
          headers: session.accessToken ? { Authorization: `Bearer ${session.accessToken}`, Accept: "application/json" } : { Accept: "application/json" },
          signal: controller.signal,
          },
        );
        const data = record(workspace.incident);
        const match = incidentId(data as IncidentRow).toLowerCase() === requestedIncidentId.toLowerCase()
          ? data as IncidentRow
          : null;
        setOperationsState(record(workspace.operations));
        setEvidenceReadModel(record(workspace.evidence));
        setDirectIncident({ loading: false, loaded: true, row: match, error: "" });
      } catch (error) {
        if (controller.signal.aborted) return;
        setOperationsState({});
        setEvidenceReadModel({});
        setDirectIncident({ loading: false, loaded: true, row: null, error: String((error as Error).message || error) });
      }
    };
    void loadRequestedIncident();
    return () => controller.abort();
  }, [directRequestVersion, requestedIncidentId, session.accessToken]);

  const directRow = directIncident.row && incidentId(directIncident.row).toLowerCase() === requestedIncidentId.toLowerCase()
    ? directIncident.row
    : null;
  // Group rows are intentionally compact and may contain source/context data
  // without the canonical recommendation. Always hydrate the detail route from
  // /incidents/{id}; use the group row only while that request is in flight.
  const row = directRow || scopedRow || undefined;
  const approval = useMemo(() => {
    if (!row) return undefined;
    const canonical = record(operationsState.approval);
    const canonicalStatus = text(canonical.status).toLowerCase();
    const feedRow = approvals.rows.find((candidate) => incidentId(candidate).toLowerCase() === incidentId(row).toLowerCase());
    if (!canonicalStatus || canonicalStatus === "not_requested") return feedRow;
    return {
      ...feedRow,
      ...canonical,
      id: text(canonical.approval_id, feedRow?.id),
      incident_id: text(canonical.incident_id, incidentId(row)),
      recommendation_id: text(canonical.recommendation_id, feedRow?.recommendation_id),
      approval_status: canonicalStatus,
      status: canonicalStatus,
    } as ApprovalRow;
  }, [approvals.rows, operationsState.approval, row]);

  if (!row && ((incidents.loading && !incidents.rows.length) || directIncident.loading || !directIncident.loaded)) return <LoadingState label="Loading incident command" />;
  if (incidents.error && !incidents.rows.length) return <ErrorState title="Incident data is temporarily unavailable" description="Kai cannot assemble the command workspace until the incident service responds." retry={incidents.refresh} />;
  if (!row && directIncident.error) return <ErrorState title="Incident data is temporarily unavailable" description={directIncident.error} retry={() => setDirectRequestVersion((version) => version + 1)} />;
  if (!row) return <EmptyState title="Incident not found" description={`No role-authorized incident record matches ${requestedIncidentId}.`} action={<button type="button" className="button-primary" onClick={() => navigate("/incidents")}>Return to incident inbox</button>} />;

  const projection = record(row.projection_payload);
  const eventPayload = record(projection.event_payload);
  const context = firstRecord(row.context, projection.context, eventPayload.context);
  const contextAlert = record(context.alert);
  const source = firstRecord(row.source_alert, projection.source_alert, contextAlert, eventPayload.alert);
  const sourceLabels = record(source.labels);
  const sourceMetadata = record(source.metadata);
  const deduplication = record(sourceMetadata.deduplication);
  const contextMetadata = record(context.metadata);
  const contextSnapshot = firstRecord(row.context_snapshot, projection.context_snapshot);
  const recommendation = firstRecord(row.recommendation, projection.recommendation, projection.remediation_recommendation, projection.resolution_plan, eventPayload.recommendation, source.recommendation);
  const recommendationMetadata = record(recommendation.metadata);
  const investigationWorkspace = record(operationsState.investigation_workspace);
  const canonicalRca = record(investigationWorkspace.rca);
  const canonicalImpact = record(investigationWorkspace.impact);
  const canonicalBinding = record(investigationWorkspace.binding);
  const canonicalResolution = record(investigationWorkspace.resolution);
  const typedClaims = Array.isArray(canonicalRca.claims) ? canonicalRca.claims.map(record) : [];
  const causalClaim = typedClaims.find((claim) => text(claim.kind).toUpperCase() === "CAUSAL") || {};
  const attachedEvidence = Array.isArray(investigationWorkspace.evidence) ? investigationWorkspace.evidence.map(record) : [];
  const attachedRequirements = Array.isArray(investigationWorkspace.requirements) ? investigationWorkspace.requirements.map(record) : [];
  const canonicalIncidentId = incidentId(row);
  const canonicalAlertId = text(
    recommendationMetadata.alert_id,
    record(record(row).incident_investigation).alert_id,
    row.alert_id,
    source.id,
    contextAlert.id,
  );
  const executionPlan = firstRecord(
    recommendation.execution_plan,
    recommendationMetadata.execution_plan,
    projection.execution_plan,
  );
  const safety = record(executionPlan.safety_envelope || recommendation.safety_envelope || projection.safety_envelope);
  const canonicalExecution = record(operationsState.execution);
  const canonicalValidation = record(operationsState.validation);
  const executionStatus = text(canonicalExecution.status).toLowerCase();
  const validation = firstRecord(
    canonicalValidation.details,
    projection.validation,
    projection.validation_result,
    projection.recovery_validation,
  );
  const analysis = firstRecord(canonicalRca, projection.analysis, projection.rca, eventPayload.analysis, eventPayload.rca, recommendation.analysis, recommendation.rca, recommendationMetadata.rca_analysis, source.analysis);
  const rootCause = text(causalClaim.statement, canonicalRca.hypothesis);
  const confidence = confidenceValue(recommendation.confidence, recommendationMetadata.confidence, analysis.confidence, eventPayload.confidence, projection.confidence, row.confidence);
  const confidenceKind = text(recommendationMetadata.confidence_kind, projection.confidence_kind).toLowerCase();
  const confidenceLabel = confidenceKind === "confirmed_rca" ? "Confirmed RCA confidence" : "Leading hypothesis confidence";
  const analysisSupportingSignals = arrayOfText(analysis.supporting_signals);
  const supportingReasons = [
    ...(analysisSupportingSignals.length ? analysisSupportingSignals : arrayOfText(analysis.evidence_used)),
    ...arrayOfText(analysis.evidence),
    ...arrayOfText(recommendationMetadata.supporting_evidence),
  ].slice(0, 6);
  const canonicalEvidenceCounts = record(evidenceReadModel.counts);
  const rcaBoundEvidenceCount = Math.max(0, Number(canonicalEvidenceCounts.rca_bound_records) || 0);
  const validatedCitationCount = Math.max(0, Number(canonicalEvidenceCounts.traceable_citations) || 0);
  const contradictions = arrayOfText(causalClaim.contradicting_evidence_ids || analysis.contradictions || analysis.ruled_out || analysis.alternative_causes);
  const declaredGaps: EvidenceGap[] = (Array.isArray(analysis.missing_evidence) ? analysis.missing_evidence : [])
    .map((gap) => typeof gap === "string"
      ? { category: gap }
      : { category: text(record(gap).category, record(gap).type), reason: text(record(gap).reason, record(gap).description) })
    .filter((gap) => gap.category);
  const status = text(operationsState.lifecycle_state, normalizedStatus(row)).toLowerCase();
  const inFailure = FAILED.some((value) => status.includes(value));
  const isTerminal = TERMINAL.some((value) => status.includes(value));
  const analysisStatus = text(causalClaim.status, analysis.status, analysis.conclusion_status, recommendationMetadata.rca_status).toLowerCase();
  const rcaConfirmed = Boolean(rootCause)
    && (confidenceKind === "confirmed_rca" || ["confirmed", "grounded", "conclusive"].includes(analysisStatus))
    && validatedCitationCount > 0;
  const currentJourneyIndex = isTerminal ? 6 : status.includes("validat") || status.includes("verif") ? 5 : status.includes("execut") || status.includes("remediat") || status.includes("rollback") ? 4 : status.includes("approval") ? 3 : rootCause ? 2 : status.includes("investigat") || status.includes("analy") ? 1 : 0;
  const resolutionReady = text(canonicalResolution.status).toLowerCase() === "ready";
  const action = resolutionReady
    ? text(canonicalResolution.catalog_operation_id, recommendation.title, recommendation.action, recommendation.recommended_action, eventPayload.recommended_action, projection.recommended_action)
    : "";
  const approvalCandidatePending = Boolean(approval) && ![
    "approved", "rejected", "completed", "expired", "not_requested",
  ].includes(text(approval?.approval_status, approval?.status).toLowerCase());
  const sourceTimestamp = text(source.received_at, source.created_at, row.created_at);
  const updatedTimestamp = text(row.latest_event_at, row.updated_at, row.created_at);
  const impact = text(canonicalImpact.statement);
  const impactEstablished = ["observed", "grounded", "established"].includes(text(canonicalImpact.status).toLowerCase());
  const sourceName = text(row.origin_system, row.source, source.origin_system, source.source, sourceLabels.origin_system, sourceLabels.transport);
  const signalCount = text(row.deduplicated_count, source.deduplicated_count, source.occurrence_count, contextAlert.deduplicated_count, contextAlert.occurrence_count);
  const correlationDetail = text(row.deduplication_reason, deduplication.reason, deduplication.disposition, deduplication.match_type) || "Correlation detail unavailable";
  const contextEvidenceCount = Math.max(0, Number(canonicalEvidenceCounts.latest_context_records) || 0);
  const contextCollectedAt = text(contextSnapshot.collected_at, contextMetadata.context_collected_at);
  const evidenceScores = Array.isArray(evidenceReadModel.scores) ? evidenceReadModel.scores : [];
  const contextQualityScore = evidenceScores.length
    ? evidenceScores.map(record).find((score) => score.key === "context_quality")
    : undefined;
  const contextQuality = Number.isFinite(Number(contextQualityScore?.percent)) ? Number(contextQualityScore?.percent) : null;
  const executionReady = executionPlan.execution_ready === true;
  const resolutionAvailable = resolutionReady && Boolean(action) && executionReady && rcaConfirmed;
  const resolutionBlocks = arrayOfText(canonicalResolution.blocking_reasons);
  const governedOperation = text(canonicalResolution.catalog_operation_id);
  const governedCapability = text(canonicalResolution.capability_id);
  const governedConnector = text(canonicalResolution.connector_id);
  const governedTarget = text(canonicalResolution.target_resource_id);
  const governedPolicy = record(canonicalResolution.policy_decision);
  const executionUnavailableReason = text(
    executionPlan.readiness_reason,
    executionPlan.blocking_reason,
    arrayOfText(executionPlan.readiness_blocks)[0],
    confidence === 0
      ? "Collect the required evidence before requesting an executable plan."
      : "The backend has not published an execution-ready governed plan.",
  );
  const approvalPending = executionReady && approvalCandidatePending;
  const validationAvailable = text(canonicalValidation.status).toLowerCase() !== "not_started"
    || Object.keys(validation).length > 0;
  const preStateObservations = Array.isArray(canonicalValidation.pre_state_observations)
    ? canonicalValidation.pre_state_observations.map(record) : [];
  const postStateObservations = Array.isArray(canonicalValidation.post_state_observations)
    ? canonicalValidation.post_state_observations.map(record) : [];
  const validationWindow = record(canonicalValidation.observation_window);
  const outcomeDecision = record(canonicalValidation.outcome_decision);
  const rollbackDecision = record(outcomeDecision.rollback);
  const knowledgeDraft = record(canonicalValidation.knowledge_draft);
  const timeline = [
    { at: row.created_at, title: "Incident record created", detail: text(row.source, row.origin_system, source.source) ? `Signal received from ${text(row.source, row.origin_system, source.source)}.` : "Source is not present in the incident record." },
    row.latest_event_type ? { at: row.latest_event_at || row.updated_at, title: text(row.latest_event_type).replaceAll("_", " "), detail: `Latest recorded lifecycle event for ${incidentId(row)}.` } : null,
    row.updated_at && row.updated_at !== row.created_at ? { at: row.updated_at, title: "Incident state updated", detail: `Current backend state is ${status.replaceAll("_", " ")}.` } : null,
  ].filter(Boolean) as Array<{ at: unknown; title: string; detail: string }>;

  const refreshIncident = async () => {
    await incidents.refresh();
    setDirectRequestVersion((version) => version + 1);
  };
  const submitClaimAmendment = async () => {
    const claimId = text(causalClaim.claim_id);
    if (!claimId || !session.accessToken) return;
    setAmendmentSubmitting(true); setAmendmentStatus("");
    try {
      const response = await fetch(`/api-gateway/incidents/${encodeURIComponent(canonicalIncidentId)}/claims/${encodeURIComponent(claimId)}/amend`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.accessToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ statement: amendmentStatement.trim(), reason: amendmentReason.trim(), source_reference: amendmentSource.trim() }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      setAmendmentStatus("Amendment recorded. The current RCA and approvals are stale while Kai runs fresh analysis.");
      setAmendmentOpen(false);
      await refreshIncident();
    } catch (reason) {
      setAmendmentStatus((reason as Error).message || "The amendment could not be recorded.");
    } finally { setAmendmentSubmitting(false); }
  };
  return <article className="incident-command">
    <header className="ic-command-header">
      <button type="button" className="ic-back" onClick={() => navigate("/incidents")}><ArrowLeft aria-hidden="true" /> Incident inbox</button>
      <div className="ic-title-row">
        <div><span className="ic-id">{incidentId(row)}</span><h2>{titleFor(row)}</h2><p>{impactEstablished ? impact : "Customer or business impact is not established by accepted evidence."}</p></div>
        <div className="ic-header-state"><StateBadge status={status} /><span><Bot aria-hidden="true" /> Kai {isTerminal ? "completed" : inFailure ? "needs intervention" : status.includes("approval") ? "needs your decision" : "is working"}</span></div>
      </div>
      <dl className="ic-critical-context">
        <div><dt>Severity</dt><dd>{valueOrUnavailable(row.severity)}</dd></div>
        <div><dt>Application</dt><dd>{valueOrUnavailable(text(projection.application, source.application, sourceLabels.application, incidents.application !== "all" ? incidents.application : ""))}</dd></div>
        <div><dt>Environment</dt><dd className={["prod", "production"].includes(text(row.environment, projection.environment, source.environment).toLowerCase()) ? "is-production" : ""}>{valueOrUnavailable(text(row.environment, projection.environment, source.environment))}</dd></div>
        <div><dt>Service</dt><dd>{valueOrUnavailable(row.service)}</dd></div>
        <div><dt>Started</dt><dd>{dateLabel(row.created_at)}</dd></div>
        <div><dt>Owner</dt><dd>{valueOrUnavailable(text(projection.owner, projection.assignee, row.jira_assignee))}</dd></div>
      </dl>
    </header>

    <section className="ic-journey" aria-label="Kai resolution journey">
      <header><div><span>Resolution journey</span><h3>From signal to verified recovery</h3></div><small>Derived from recorded lifecycle state</small></header>
      <ol>{JOURNEY.map((stage, index) => <li key={stage} className={index < currentJourneyIndex ? "is-complete" : index === currentJourneyIndex ? inFailure ? "is-failed" : "is-current" : "is-pending"}><i>{index < currentJourneyIndex ? <Check /> : index === currentJourneyIndex && inFailure ? <X /> : index + 1}</i><span>{stage}</span>{index < JOURNEY.length - 1 ? <ChevronRight aria-hidden="true" /> : null}</li>)}</ol>
    </section>

    {inFailure ? <section className="ic-failure" role="alert"><AlertTriangle aria-hidden="true" /><div><span>Resolution did not reach verified recovery</span><strong>{text(validation.message, projection.failure_reason, projection.error) || "The backend marked this incident as failed without a human-readable reason."}</strong><p>{status.includes("rollback") ? "Rollback state is recorded in the incident lifecycle." : "Review the technical record before choosing another action."}</p></div></section> : null}

    <div className="ic-command-grid">
      <main className="ic-primary">
        <section className="ic-section ic-impact">
          <header><div><span>Observed state</span><h3>{impactEstablished ? "Verified impact" : "Impact has not been established"}</h3></div><StatusBadge tone={impactEstablished ? "success" : "warning"}>{impactEstablished ? "Evidence-backed" : "Unknown"}</StatusBadge></header>
          <p className="ic-decision-summary">{impactEstablished ? impact : "The alert proves that a signal fired. It does not, by itself, prove customer or business impact."}</p>
          <div className="ic-impact-grid"><Metric label="Impact" value={impactEstablished ? impact : "Not established"} /><Metric label="Monitored service" value={valueOrUnavailable(row.service)} /><Metric label="Signal source" value={valueOrUnavailable(sourceName)} /><Metric label="Correlated signals" value={valueOrUnavailable(signalCount)} detail={correlationDetail} /></div>
        </section>

        <section className="ic-section ic-rca">
          <header><div><span>{rcaConfirmed ? "Confirmed root cause" : "Working hypothesis"}{canonicalBinding.rca_version ? ` · RCA v${canonicalBinding.rca_version}` : ""}</span><h3>{rootCause || "No causal hypothesis has been published"}</h3></div><StatusBadge tone={rcaConfirmed ? "success" : rootCause ? "warning" : "inactive"}>{rcaConfirmed ? "Grounded" : rootCause ? text(canonicalRca.status, "Unconfirmed").replaceAll("_", " ") : "Unavailable"}</StatusBadge></header>
          {rootCause ? <>
            <div className="ic-decision-evidence"><span><strong>{validatedCitationCount}</strong> validated citation{validatedCitationCount === 1 ? "" : "s"}</span><span><strong>{rcaBoundEvidenceCount}</strong> RCA-bound evidence record{rcaBoundEvidenceCount === 1 ? "" : "s"}</span><span><strong>{confidence === null ? "—" : `${confidence}%`}</strong> {confidenceLabel.toLowerCase()}</span></div>
            <div className="ic-reasoning"><article><h4>Why Kai thinks this</h4>{supportingReasons.length ? <ul>{supportingReasons.map((reason) => <li key={reason}><CheckCircle2 aria-hidden="true" />{reason}</li>)}</ul> : <p>Supporting reasons were not included in the backend analysis.</p>}</article><article><h4>What Kai ruled out</h4>{contradictions.length ? <ul>{contradictions.map((reason) => <li key={reason}><X aria-hidden="true" />{reason}</li>)}</ul> : <p>No ruled-out hypotheses were included.</p>}</article></div>
            <TechnicalDetails summary="Why is this gated?"><p>{rcaConfirmed ? "The backend marked this analysis as grounded and supplied validated citations." : "This remains a diagnostic hypothesis. Confidence alone cannot confirm causality or authorize remediation."}</p><p>{validatedCitationCount} validated citation(s), {supportingReasons.length} supporting reason(s), and {contradictions.length} contradicting evidence item(s) are bound to this view.</p>{text(causalClaim.falsification_test) ? <p><strong>Test next:</strong> {text(causalClaim.falsification_test)}</p> : null}</TechnicalDetails>
            {text(causalClaim.claim_id) ? <div className="ic-amendment">
              <button type="button" className="button-secondary" onClick={() => { setAmendmentOpen((open) => !open); setAmendmentStatement(rootCause); }}>Correct this AI claim</button>
              {amendmentOpen ? <div className="ic-amendment-form">
                <p>This records an operator amendment. It does not become evidence until fresh analysis verifies the cited source.</p>
                <label>Corrected claim<textarea value={amendmentStatement} onChange={(event) => setAmendmentStatement(event.target.value)} /></label>
                <label>Why it needs correction<textarea value={amendmentReason} onChange={(event) => setAmendmentReason(event.target.value)} /></label>
                <label>Source reference<input value={amendmentSource} onChange={(event) => setAmendmentSource(event.target.value)} placeholder="https://ticket, dashboard, trace, or runbook" /></label>
                <button type="button" className="button-primary" disabled={amendmentSubmitting || amendmentStatement.trim().length < 10 || amendmentReason.trim().length < 10 || !amendmentSource.includes("://")} onClick={() => void submitClaimAmendment()}>{amendmentSubmitting ? "Recording…" : "Record amendment and rerun RCA"}</button>
              </div> : null}
              {amendmentStatus ? <p role="status">{amendmentStatus}</p> : null}
            </div> : null}
          </> : <EmptyState title="Investigation is still forming a hypothesis" description="Kai will show a falsifiable root-cause story when the backend publishes one." />}
        </section>

        <section className="ic-section ic-investigation-records">
          <header><div><span>Full investigation</span><h3>Attached evidence and open requirements</h3></div><StatusBadge tone={attachedRequirements.length ? "warning" : "success"}>{attachedEvidence.length} evidence · {attachedRequirements.length} requirements</StatusBadge></header>
          {attachedEvidence.length ? <ul className="ic-attached-records">{attachedEvidence.map((item, index) => <li key={text(item.evidence_id, index)}><div><strong>{valueOrUnavailable(text(item.category))}</strong><span>{valueOrUnavailable(text(item.connector, item.source_id))}</span></div><p>{valueOrUnavailable(text(item.citation))}</p><small>{item.accepted_for_rca === true ? "Accepted for RCA" : "Attached context"} · {valueOrUnavailable(text(item.freshness))}</small></li>)}</ul> : <p className="ic-unavailable">No canonical evidence records are attached to this investigation.</p>}
          {attachedRequirements.length ? <div className="ic-open-requirements"><h4>Evidence still required</h4><ul>{attachedRequirements.map((item, index) => <li key={text(item.requirement_id, index)}><strong>{valueOrUnavailable(text(item.category))}</strong><span>{valueOrUnavailable(text(item.question, item.reason))}</span><em>{valueOrUnavailable(text(item.status))}</em></li>)}</ul></div> : null}
        </section>

        <ContextEnrichmentPanel
          incidentId={canonicalIncidentId}
          alertId={canonicalAlertId || undefined}
          accessToken={session.accessToken || ""}
          declaredGaps={declaredGaps}
          proposedRcaDraft={rootCause}
          onIncidentRefresh={refreshIncident}
        />

        <section className="ic-section ic-causal">
          <header><div><span>Causal chain</span><h3>{rcaConfirmed && impactEstablished ? "Evidence-supported path to impact" : "Causal path is incomplete"}</h3></div><GitBranch aria-hidden="true" /></header>
          <div className="ic-causal-path">
            <div><button type="button"><span>Observed signal</span><strong>{titleFor(row)}</strong></button><ArrowDown aria-hidden="true" /></div>
            <div><button type="button"><span>Monitored service</span><strong>{valueOrUnavailable(row.service)}</strong></button><ArrowDown aria-hidden="true" /></div>
            <div><button type="button"><span>{rcaConfirmed ? "Confirmed cause" : "Unconfirmed hypothesis"}</span><strong>{rootCause || "Not available"}</strong></button><ArrowDown aria-hidden="true" /></div>
            <div><button type="button"><span>{impactEstablished ? "Verified impact" : "Impact"}</span><strong>{impactEstablished ? impact : "Not established"}</strong></button></div>
          </div>
          {!rcaConfirmed || !impactEstablished ? <p className="ic-gate-note"><ShieldCheck aria-hidden="true" /> KaiMS will not claim an end-to-end causal path until both causality and impact are supported by accepted evidence.</p> : null}
        </section>

        <section className="ic-section ic-resolution">
          <header><div><span>{resolutionAvailable ? "Governed resolution" : "Resolution gate"}</span><h3>{resolutionAvailable ? action : "No executable resolution is available"}</h3></div><StatusBadge tone={resolutionAvailable ? "success" : "warning"}>{resolutionAvailable ? "Ready for review" : "Blocked"}</StatusBadge></header>
          {resolutionAvailable ? <>
            <p className="ic-resolution-why">{text(recommendation.why, recommendation.rationale, recommendation.reason, projection.recommendation_reason) || "The backend did not include a human-readable rationale."}</p>
            <div className="ic-resolution-facts">
              <Metric label="Risk" value={valueOrUnavailable(text(recommendation.risk_tier, row.risk_tier))} />
              <Metric label="Blast radius" value={valueOrUnavailable(text(recommendation.blast_radius, executionPlan.blast_radius, safety.allowed_scope))} />
              <Metric label="Target" value={valueOrUnavailable(governedTarget)} />
              <Metric label="Catalog operation" value={valueOrUnavailable(governedOperation)} />
              <Metric label="Capability" value={valueOrUnavailable(governedCapability)} />
              <Metric label="Connector" value={valueOrUnavailable(governedConnector)} />
              <Metric label="Expected duration" value={valueOrUnavailable(text(recommendation.expected_duration, executionPlan.expected_duration))} />
              <Metric label="Execution" value={executionStatus && executionStatus !== "not_started" ? executionStatus.replaceAll("_", " ") : "Not started"} />
              <Metric label="Rollback" value={canonicalResolution.rollback_bound === true ? "Bound to plan" : "Not bound"} />
            </div>
            <section className="ic-safety-envelope"><header><ShieldCheck aria-hidden="true" /><div><span>Execution safety envelope</span><strong>Backend policy remains authoritative</strong></div></header><dl>{[
              ["Allowed scope", safety.allowed_scope || executionPlan.scope],
              ["Traffic exposure", safety.traffic_exposure || executionPlan.traffic_exposure],
              ["Automatic stop", safety.automatic_stop || safety.stop_conditions],
              ["Rollback", safety.rollback || executionPlan.rollback],
              ["Approval", safety.approval || row.approval_status || (approvalPending ? "Required" : "Not recorded")],
            ].map(([label, value]) => <div key={String(label)}><dt>{String(label)}</dt><dd>{valueOrUnavailable(Array.isArray(value) ? value.join("; ") : value)}</dd></div>)}</dl></section>
            {approvalPending && approval ? <section className="ic-inline-approval"><header><FileCheck2 aria-hidden="true" /><div><span>Kai needs your decision</span><strong>{action || "Review this production action"}</strong></div></header><p>{text(row.environment).toLowerCase().includes("prod") ? "This action may change Production. Review its scope and stop conditions before approving." : "Policy requires a human decision before Kai can continue."}</p>{approvalExpanded ? <div className="ic-approval-preview"><article><span>What will change</span><p>{action || "Action detail unavailable"}</p></article><article><span>What Kai will watch</span><p>{valueOrUnavailable(safety.stop_conditions || validation.watch_conditions)}</p></article><article><span>When Kai will rollback</span><p>{valueOrUnavailable(safety.rollback_conditions || executionPlan.rollback_conditions)}</p></article></div> : null}<div className="ic-decision-actions"><button type="button" className="button-secondary" onClick={() => setApprovalExpanded((open) => !open)}>{approvalExpanded ? "Hide preview" : "Review safety preview"}</button><button type="button" className="button-secondary" onClick={() => approvals.toggleReject(incidentId(approval))}>Reject</button><button type="button" className="button-primary" disabled={!approvals.ready || approvals.actionLoading} onClick={() => approvals.approve(approval as ApprovalRow)}>{approvals.actionLoading ? "Submitting decision..." : "Approve & let Kai resolve"}</button></div>{approvals.actionError ? <p className="ic-action-error">{approvals.actionError}</p> : null}</section> : <div className="ic-resolution-actions"><button type="button" className="button-secondary" disabled={!executionReady} title={!executionReady ? executionUnavailableReason : undefined} onClick={() => incidents.openTechnical(row, "resolution")}>{executionReady ? "Open technical execution workspace" : "Execution unavailable — collect evidence"}</button>{row.jira_url ? <a className="button-secondary" href={row.jira_url} target="_blank" rel="noreferrer">Open ticket <ExternalLink aria-hidden="true" /></a> : null}</div>}
          </> : <div className="ic-resolution-blocked"><ShieldCheck aria-hidden="true" /><div><strong>Resolution is blocked by the full investigation</strong><p>{resolutionBlocks.length ? `Required before resolution: ${resolutionBlocks.join(", ")}.` : "Kai will keep collecting evidence until the backend publishes a grounded RCA and a governed execution plan."}</p><dl><div><dt>Grounded RCA</dt><dd>{rcaConfirmed ? "Passed" : "Required"}</dd></div><div><dt>Validated citations</dt><dd>{validatedCitationCount}</dd></div><div><dt>Catalog operation</dt><dd>{governedOperation || "Not selected"}</dd></div><div><dt>Registered capability</dt><dd>{governedCapability || "Not bound"}</dd></div><div><dt>Target / connector</dt><dd>{governedTarget && governedConnector ? `${governedTarget} via ${governedConnector}` : "Not bound"}</dd></div><div><dt>Safety bindings</dt><dd>{canonicalResolution.credential_bound === true && canonicalResolution.rollback_bound === true ? "Credential and rollback bound" : "Incomplete"}</dd></div><div><dt>Policy</dt><dd>{text(governedPolicy.decision, governedPolicy.status) || "Not evaluated"}</dd></div><div><dt>Execution-ready plan</dt><dd>{executionReady ? "Published" : "Required"}</dd></div></dl></div></div>}
        </section>

        <section className="ic-section ic-validation">
          <header><div><span>Recovery validation</span><h3>{validationAvailable ? text(canonicalValidation.status, validation.status, validation.result, "Validation evidence") : "Validation has not started"}</h3></div>{validationAvailable ? <SearchCheck aria-hidden="true" /> : <Clock3 aria-hidden="true" />}</header>
          {validationAvailable ? <>
            <div className="ic-resolution-facts">
              <Metric label="Outcome" value={valueOrUnavailable(text(outcomeDecision.outcome, canonicalValidation.status))} />
              <Metric label="Observation window" value={validationWindow.required_seconds ? `${validationWindow.elapsed_seconds || 0}s / ${validationWindow.required_seconds}s` : "Not recorded"} />
              <Metric label="Pre-state samples" value={String(preStateObservations.length)} />
              <Metric label="Post-state samples" value={String(postStateObservations.length)} />
              <Metric label="Rollback decision" value={valueOrUnavailable(text(rollbackDecision.disposition))} />
              <Metric label="Knowledge draft" value={text(knowledgeDraft.status) || "Not created"} />
            </div>
            {postStateObservations.length ? <div className="ic-validation-grid"><span>Validator</span><span>Before</span><span>After</span><span>Target</span>{postStateObservations.slice(0, 8).map((post, index) => { const prior = preStateObservations.find((item) => text(item.validator_id) === text(post.validator_id)); return <div className="ic-validation-row" key={`${text(post.validator_id)}-${index}`}><strong>{text(post.kind, post.validator_id).replaceAll("_", " ")}</strong><span>{prior ? valueOrUnavailable(prior.measured_value ?? prior.passed) : "Not recorded"}</span><span>{valueOrUnavailable(post.measured_value ?? post.passed)}</span><span>{valueOrUnavailable(post.expected_value ?? post.target_resource_id)}</span></div>; })}</div> : <p className="ic-unavailable">Validation exists, but no immutable post-state observations were published.</p>}
            {knowledgeDraft.status ? <p className="ic-gate-note"><ShieldCheck aria-hidden="true" /> Recovery knowledge is a {text(knowledgeDraft.status)} draft and cannot enter production retrieval until a governance owner reviews and approves it.</p> : null}
          </> : <EmptyState title="Waiting for execution evidence" description="Kai will compare the recorded pre-state and post-state when validation begins." />}
        </section>
      </main>

      <aside className="ic-intelligence">
        <section className="ic-kai-panel"><header><span><Bot aria-hidden="true" />Kai intelligence</span><i>{inFailure ? "Attention" : isTerminal ? "Recovered" : "Live context"}</i></header><div className="ic-kai-state"><Sparkles aria-hidden="true" /><span><small>Current state</small><strong>{isTerminal ? "Recovery recorded" : status.replaceAll("_", " ")}</strong></span></div></section>
        <section className="ic-narrative"><header><span>Live narrative</span><h3>What Kai knows so far</h3></header>{timeline.length ? <ol>{timeline.map((event, index) => <li key={`${event.title}-${index}`}><time>{dateLabel(event.at)}</time><i /><div><strong>{event.title}</strong><p>{event.detail}</p></div></li>)}</ol> : <p>No timestamped lifecycle events are available.</p>}<small>Only recorded lifecycle events are shown; internal agent activity is not fabricated.</small></section>
        <section className="ic-evidence"><header><span>Evidence provenance</span><h3>Sources supporting this view</h3></header><article><div><strong>{sourceName || "Incident service"}</strong><em>{sourceTimestamp && Date.now() - new Date(sourceTimestamp).getTime() < 300_000 ? "LIVE" : "RECENT"}</em></div><p>Collected {ageLabel(sourceTimestamp)}</p><small>Evidence ID: {text(row.alert_id, source.id, row.fingerprint, "Unavailable")}</small></article>{Object.keys(context).length || Object.keys(contextSnapshot).length ? <article><div><strong>Kai context record</strong><em>RECORDED</em></div><p>{contextEvidenceCount ? `${contextEvidenceCount} evidence records` : "Context evidence retained"}{contextQuality !== null ? ` · ${contextQuality}% quality` : ""}</p><small>{contextCollectedAt ? `Collected ${ageLabel(contextCollectedAt)}` : contextMetadata.recovered ? "Recovered from durable alert and recommendation records" : `Snapshot: ${text(contextSnapshot.snapshot_id, contextMetadata.context_fingerprint, "persisted")}`}</small></article> : null}{rootCause ? <article><div><strong>Kai analysis</strong><em className="is-inferred">INFERRED</em></div><p>Updated {ageLabel(updatedTimestamp)}</p><small>Inference is visually separated from telemetry.</small></article> : null}</section>
        <section className="ic-control"><header><PauseCircle aria-hidden="true" /><div><span>Human control</span><h3>Stay in command</h3></div></header><p>{executionReady ? "Holding, taking control, or rolling back requires an authoritative execution capability." : executionUnavailableReason}</p><button type="button" disabled={!executionReady} title={!executionReady ? executionUnavailableReason : undefined} onClick={() => incidents.openTechnical(row, "resolution")}><Gauge aria-hidden="true" /> {executionReady ? "Take control in governed workspace" : "No execution to control"}</button><button type="button" disabled title="Available only when the backend reports an active, controllable execution"><RotateCcw aria-hidden="true" /> Rollback unavailable</button></section>
      </aside>
    </div>

    <footer className="ic-truth-note"><ShieldCheck aria-hidden="true" /><span><strong>Operational truth policy:</strong> unavailable backend fields stay unavailable. KaiMS does not invent confidence, execution progress, safety controls, or recovery results. <small>UI {RELEASE_SHA.slice(0, 12)} · Gateway {backendReleaseSha ? backendReleaseSha.slice(0, 12) : "unavailable"}</small></span><button type="button" onClick={() => { incidents.refresh(); setDirectRequestVersion((version) => version + 1); }}><RefreshCw aria-hidden="true" /> Refresh incident</button></footer>
  </article>;
}
