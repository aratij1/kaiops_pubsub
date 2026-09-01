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
  History,
  PauseCircle,
  RefreshCw,
  RotateCcw,
  SearchCheck,
  ShieldCheck,
  Sparkles,
  Target,
  Wrench,
  X,
} from "lucide-react";

import { useRouteRuntimeSlice, type ApprovalRow, type IncidentRow } from "../../app/routeRuntime";
import { EmptyState, ErrorState, LoadingState, StatusBadge, TechnicalDetails } from "../../components/design-system";
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
  const [approvalExpanded, setApprovalExpanded] = useState(false);
  const [directRequestVersion, setDirectRequestVersion] = useState(0);
  const [directIncident, setDirectIncident] = useState<{
    loading: boolean;
    loaded: boolean;
    row: IncidentRow | null;
    error: string;
  }>({ loading: false, loaded: false, row: null, error: "" });

  const requestedIncidentId = useMemo(() => decodeURIComponent(routeIncidentId).trim(), [routeIncidentId]);
  const scopedRow = useMemo(() => incidents.rows.find((candidate) => incidentId(candidate).toLowerCase() === requestedIncidentId.toLowerCase()), [incidents.rows, requestedIncidentId]);
  useEffect(() => {
    if (!requestedIncidentId) {
      setDirectIncident({ loading: false, loaded: true, row: null, error: "" });
      return undefined;
    }
    const controller = new AbortController();
    const loadRequestedIncident = async () => {
      setDirectIncident((current) => ({ ...current, loading: true, loaded: false, error: "" }));
      try {
        const response = await fetch(`/api-gateway/incidents/${encodeURIComponent(requestedIncidentId)}`, {
          headers: session.accessToken ? { Authorization: `Bearer ${session.accessToken}`, Accept: "application/json" } : { Accept: "application/json" },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Incident service returned HTTP ${response.status}`);
        const payload = record(await response.json() as unknown);
        const data = Object.keys(record(payload.data)).length ? record(payload.data) : payload;
        const match = incidentId(data as IncidentRow).toLowerCase() === requestedIncidentId.toLowerCase()
          ? data as IncidentRow
          : null;
        setDirectIncident({ loading: false, loaded: true, row: match, error: "" });
      } catch (error) {
        if (controller.signal.aborted) return;
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
  const approval = useMemo(() => row ? approvals.rows.find((candidate) => incidentId(candidate).toLowerCase() === incidentId(row).toLowerCase()) : undefined, [approvals.rows, row]);

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
  const sourceAnnotations = record(source.annotations);
  const sourceMetadata = record(source.metadata);
  const deduplication = record(sourceMetadata.deduplication);
  const contextMetadata = record(context.metadata);
  const contextSnapshot = firstRecord(row.context_snapshot, projection.context_snapshot);
  const contextSourceManifest = record(contextSnapshot.source_manifest);
  const recommendation = firstRecord(row.recommendation, projection.recommendation, projection.remediation_recommendation, projection.resolution_plan, eventPayload.recommendation, source.recommendation);
  const recommendationMetadata = record(recommendation.metadata);
  const executionPlan = firstRecord(
    recommendation.execution_plan,
    recommendationMetadata.execution_plan,
    projection.execution_plan,
  );
  const safety = record(executionPlan.safety_envelope || recommendation.safety_envelope || projection.safety_envelope);
  const validation = record(projection.validation || projection.validation_result || projection.recovery_validation);
  const before = record(validation.before || validation.pre_state);
  const after = record(validation.after || validation.post_state);
  const analysis = firstRecord(projection.analysis, projection.rca, eventPayload.analysis, eventPayload.rca, recommendation.analysis, recommendation.rca, source.analysis);
  const rootCause = text(row.root_cause, projection.root_cause, eventPayload.root_cause, analysis.root_cause, analysis.leading_hypothesis, recommendation.root_cause, recommendationMetadata.root_cause, sourceAnnotations.root_cause);
  const confidence = confidenceValue(row.confidence, projection.confidence, eventPayload.confidence, analysis.confidence, recommendation.confidence, recommendationMetadata.confidence);
  const supportingReasons = [
    ...arrayOfText(analysis.supporting_signals),
    ...arrayOfText(analysis.evidence),
    ...arrayOfText(recommendationMetadata.supporting_evidence),
  ].slice(0, 6);
  const contradictions = arrayOfText(analysis.contradictions || analysis.ruled_out);
  const status = normalizedStatus(row);
  const inFailure = FAILED.some((value) => status.includes(value));
  const isTerminal = TERMINAL.some((value) => status.includes(value));
  const currentJourneyIndex = isTerminal ? 6 : status.includes("validat") || status.includes("verif") ? 5 : status.includes("execut") || status.includes("remediat") || status.includes("rollback") ? 4 : status.includes("approval") || recommendation.action || recommendation.title ? 3 : rootCause ? 2 : status.includes("investigat") || status.includes("analy") ? 1 : 0;
  const action = text(recommendation.title, recommendation.action, recommendation.recommended_action, eventPayload.recommended_action, projection.recommended_action);
  const rawResolutionRationale = text(recommendation.why, recommendation.rationale, recommendation.reason, projection.recommendation_reason);
  const resolutionRationale = /proposed the RCA with 0 validated evidence citation\(s\); confidence=0(?:\.0+)?\.?/i.test(rawResolutionRationale)
    ? `No validated causal evidence citations support this RCA. The published ${confidence ?? 0}% score is bounded diagnostic confidence only and does not authorize execution.`
    : rawResolutionRationale;
  const approvalCandidatePending = Boolean(approval) && !["approved", "rejected", "completed"].includes(text(approval?.approval_status, approval?.status).toLowerCase());
  const sourceTimestamp = text(source.received_at, source.created_at, row.created_at);
  const updatedTimestamp = text(row.latest_event_at, row.updated_at, row.created_at);
  const impact = text(row.customer_impact, row.business_impact, projection.customer_impact, projection.business_impact, projection.impact, eventPayload.impact, recommendation.impact, sourceAnnotations.business_impact, sourceAnnotations.summary, source.summary, source.description, row.summary);
  const sourceName = text(row.origin_system, row.source, source.origin_system, source.source, sourceLabels.origin_system, sourceLabels.transport);
  const signalCount = text(row.deduplicated_count, source.deduplicated_count, source.occurrence_count, contextAlert.deduplicated_count, contextAlert.occurrence_count);
  const correlationDetail = text(row.deduplication_reason, deduplication.reason, deduplication.disposition, deduplication.match_type) || "Correlation detail unavailable";
  const contextEvidenceCount = Object.values(contextSourceManifest).reduce<number>((total, entry) => {
    const resultCount = Number(record(entry).result_count || record(entry).fresh_count || 0);
    return total + (Number.isFinite(resultCount) ? resultCount : 0);
  }, 0);
  const contextCollectedAt = text(contextSnapshot.collected_at, contextMetadata.context_collected_at);
  const contextQuality = confidenceValue(contextSnapshot.quality_score);
  const resolutionAvailable = Boolean(action || Object.keys(executionPlan).length);
  const executionReady = executionPlan.execution_ready === true;
  const executionUnavailableReason = text(
    executionPlan.readiness_reason,
    executionPlan.blocking_reason,
    arrayOfText(executionPlan.readiness_blocks)[0],
    confidence === 0
      ? "Collect the required evidence before requesting an executable plan."
      : "The backend has not published an execution-ready governed plan.",
  );
  const approvalPending = executionReady && approvalCandidatePending;
  const validationAvailable = Object.keys(validation).length > 0;
  const timeline = [
    { at: row.created_at, title: "Incident record created", detail: text(row.source, row.origin_system, source.source) ? `Signal received from ${text(row.source, row.origin_system, source.source)}.` : "Source is not present in the incident record." },
    row.latest_event_type ? { at: row.latest_event_at || row.updated_at, title: text(row.latest_event_type).replaceAll("_", " "), detail: `Latest recorded lifecycle event for ${incidentId(row)}.` } : null,
    row.updated_at && row.updated_at !== row.created_at ? { at: row.updated_at, title: "Incident state updated", detail: `Current backend state is ${status.replaceAll("_", " ")}.` } : null,
  ].filter(Boolean) as Array<{ at: unknown; title: string; detail: string }>;

  return <article className="incident-command">
    <header className="ic-command-header">
      <button type="button" className="ic-back" onClick={() => navigate("/incidents")}><ArrowLeft aria-hidden="true" /> Incident inbox</button>
      <div className="ic-title-row">
        <div><span className="ic-id">{incidentId(row)}</span><h2>{titleFor(row)}</h2><p>{impact || "Customer and business impact have not been published to this incident."}</p></div>
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
          <header><div><span>What happened</span><h3>Impact and service context</h3></div><Target aria-hidden="true" /></header>
          <div className="ic-impact-grid"><Metric label="Customer impact" value={impact || "Unavailable"} /><Metric label="Affected service" value={valueOrUnavailable(row.service)} /><Metric label="Source" value={valueOrUnavailable(sourceName)} /><Metric label="Signal count" value={valueOrUnavailable(signalCount)} detail={correlationDetail} /></div>
        </section>

        <section className="ic-section ic-rca">
          <header><div><span>Root cause story</span><h3>{rootCause || "Kai has not published a root-cause hypothesis"}</h3></div>{confidence !== null ? <div className="ic-confidence"><small>{confidence >= 80 ? "High" : confidence >= 60 ? "Medium" : "Low"} confidence</small><strong>{confidence}%</strong></div> : <StatusBadge tone="inactive">Confidence unavailable</StatusBadge>}</header>
          {rootCause ? <>
            <div className="ic-reasoning"><article><h4>Why Kai thinks this</h4>{supportingReasons.length ? <ul>{supportingReasons.map((reason) => <li key={reason}><CheckCircle2 aria-hidden="true" />{reason}</li>)}</ul> : <p>Supporting reasons were not included in the backend analysis.</p>}</article><article><h4>What Kai ruled out</h4>{contradictions.length ? <ul>{contradictions.map((reason) => <li key={reason}><X aria-hidden="true" />{reason}</li>)}</ul> : <p>No ruled-out hypotheses were included.</p>}</article></div>
            <TechnicalDetails summary="Why this confidence?"><p>{confidence === null ? "The backend did not publish a confidence score." : `${confidence}% is the normalized score published with this incident analysis.`}</p><p>{supportingReasons.length} supporting reason(s) and {contradictions.length} contradiction or ruled-out item(s) are available.</p></TechnicalDetails>
          </> : <EmptyState title="Investigation is still forming a hypothesis" description="Kai will show a falsifiable root-cause story when the backend publishes one." />}
        </section>

        <section className="ic-section ic-causal">
          <header><div><span>Relevant causal path</span><h3>How the signal connects to impact</h3></div><GitBranch aria-hidden="true" /></header>
          <div className="ic-causal-path">
            {[text(rootCause), text(row.service), titleFor(row), impact].filter((value, index, values) => value && values.indexOf(value) === index).map((value, index, values) => <div key={value}><button type="button"><span>{index === 0 && rootCause ? "Hypothesis" : index === values.length - 1 ? "Observed impact" : "Affected component"}</span><strong>{value}</strong></button>{index < values.length - 1 ? <ArrowDown aria-hidden="true" /> : null}</div>)}
          </div>
          {!rootCause && !impact ? <p className="ic-unavailable">The backend has not supplied enough evidence to construct a causal path.</p> : null}
        </section>

        <section className="ic-section ic-resolution">
          <header><div><span>Recommended resolution</span><h3>{action || "No resolution recommendation available"}</h3></div><Wrench aria-hidden="true" /></header>
          {resolutionAvailable ? <>
            <p className="ic-resolution-why">{resolutionRationale || "The backend did not include a human-readable rationale."}</p>
            <div className="ic-resolution-facts">
              <Metric label="Risk" value={valueOrUnavailable(text(recommendation.risk_tier, row.risk_tier))} />
              <Metric label="Blast radius" value={valueOrUnavailable(text(recommendation.blast_radius, executionPlan.blast_radius, safety.allowed_scope))} />
              <Metric label="Target" value={valueOrUnavailable(text(recommendation.target, executionPlan.target, row.service))} />
              <Metric label="Strategy" value={valueOrUnavailable(text(recommendation.strategy, executionPlan.strategy))} />
              <Metric label="Expected duration" value={valueOrUnavailable(text(recommendation.expected_duration, executionPlan.expected_duration))} />
              <Metric label="Rollback" value={valueOrUnavailable(text(recommendation.rollback, executionPlan.rollback, safety.rollback))} />
            </div>
            <section className="ic-safety-envelope"><header><ShieldCheck aria-hidden="true" /><div><span>Execution safety envelope</span><strong>Backend policy remains authoritative</strong></div></header><dl>{[
              ["Allowed scope", safety.allowed_scope || executionPlan.scope],
              ["Traffic exposure", safety.traffic_exposure || executionPlan.traffic_exposure],
              ["Automatic stop", safety.automatic_stop || safety.stop_conditions],
              ["Rollback", safety.rollback || executionPlan.rollback],
              ["Approval", safety.approval || row.approval_status || (approvalPending ? "Required" : "Not recorded")],
            ].map(([label, value]) => <div key={String(label)}><dt>{String(label)}</dt><dd>{valueOrUnavailable(Array.isArray(value) ? value.join("; ") : value)}</dd></div>)}</dl></section>
            {approvalPending && approval ? <section className="ic-inline-approval"><header><FileCheck2 aria-hidden="true" /><div><span>Kai needs your decision</span><strong>{action || "Review this production action"}</strong></div></header><p>{text(row.environment).toLowerCase().includes("prod") ? "This action may change Production. Review its scope and stop conditions before approving." : "Policy requires a human decision before Kai can continue."}</p>{approvalExpanded ? <div className="ic-approval-preview"><article><span>What will change</span><p>{action || "Action detail unavailable"}</p></article><article><span>What Kai will watch</span><p>{valueOrUnavailable(safety.stop_conditions || validation.watch_conditions)}</p></article><article><span>When Kai will rollback</span><p>{valueOrUnavailable(safety.rollback_conditions || executionPlan.rollback_conditions)}</p></article></div> : null}<div className="ic-decision-actions"><button type="button" className="button-secondary" onClick={() => setApprovalExpanded((open) => !open)}>{approvalExpanded ? "Hide preview" : "Review safety preview"}</button><button type="button" className="button-secondary" onClick={() => approvals.toggleReject(incidentId(approval))}>Reject</button><button type="button" className="button-primary" disabled={!approvals.ready || approvals.actionLoading} onClick={() => approvals.approve(approval as ApprovalRow)}>{approvals.actionLoading ? "Submitting decision..." : "Approve & let Kai resolve"}</button></div>{approvals.actionError ? <p className="ic-action-error">{approvals.actionError}</p> : null}</section> : <div className="ic-resolution-actions"><button type="button" className="button-secondary" disabled={!executionReady} title={!executionReady ? executionUnavailableReason : undefined} onClick={() => incidents.openTechnical(row, "resolution")}>{executionReady ? "Open technical execution workspace" : "Execution unavailable — collect evidence"}</button>{row.jira_url ? <a className="button-secondary" href={row.jira_url} target="_blank" rel="noreferrer">Open ticket <ExternalLink aria-hidden="true" /></a> : null}</div>}
          </> : <EmptyState title="No safe action is ready" description="Kai will keep investigating until the backend publishes a governed resolution plan." />}
        </section>

        <section className="ic-section ic-validation">
          <header><div><span>Recovery validation</span><h3>{validationAvailable ? text(validation.status, validation.result, "Validation evidence") : "Validation has not started"}</h3></div>{validationAvailable ? <SearchCheck aria-hidden="true" /> : <Clock3 aria-hidden="true" />}</header>
          {validationAvailable ? <><div className="ic-validation-grid"><span>Signal</span><span>Before</span><span>After</span><span>Target</span>{Array.from(new Set([...Object.keys(before), ...Object.keys(after)])).slice(0, 8).map((key) => <div className="ic-validation-row" key={key}><strong>{key.replaceAll("_", " ")}</strong><span>{valueOrUnavailable(before[key])}</span><span>{valueOrUnavailable(after[key])}</span><span>{valueOrUnavailable(record(validation.targets)[key])}</span></div>)}</div>{!Object.keys(before).length && !Object.keys(after).length ? <p className="ic-unavailable">A validation status exists, but before/after measurements were not published.</p> : null}</> : <EmptyState title="Waiting for execution evidence" description="Kai will compare the recorded pre-state and post-state when validation begins." />}
        </section>
      </main>

      <aside className="ic-intelligence">
        <section className="ic-kai-panel"><header><span><Bot aria-hidden="true" />Kai intelligence</span><i>{inFailure ? "Attention" : isTerminal ? "Recovered" : "Live context"}</i></header><div className="ic-kai-state"><Sparkles aria-hidden="true" /><span><small>Current state</small><strong>{isTerminal ? "Recovery recorded" : status.replaceAll("_", " ")}</strong></span></div><button type="button" onClick={() => incidents.openTechnical(row, "overview")}><SearchCheck aria-hidden="true" /> Open full investigation</button></section>
        <section className="ic-narrative"><header><span>Live narrative</span><h3>What Kai knows so far</h3></header>{timeline.length ? <ol>{timeline.map((event, index) => <li key={`${event.title}-${index}`}><time>{dateLabel(event.at)}</time><i /><div><strong>{event.title}</strong><p>{event.detail}</p></div></li>)}</ol> : <p>No timestamped lifecycle events are available.</p>}<small>Only recorded lifecycle events are shown; internal agent activity is not fabricated.</small></section>
        <section className="ic-evidence"><header><span>Evidence provenance</span><h3>Sources supporting this view</h3></header><article><div><strong>{sourceName || "Incident service"}</strong><em>{sourceTimestamp && Date.now() - new Date(sourceTimestamp).getTime() < 300_000 ? "LIVE" : "RECENT"}</em></div><p>Collected {ageLabel(sourceTimestamp)}</p><small>Evidence ID: {text(row.alert_id, source.id, row.fingerprint, "Unavailable")}</small></article>{Object.keys(context).length || Object.keys(contextSnapshot).length ? <article><div><strong>Kai context record</strong><em>RECORDED</em></div><p>{contextEvidenceCount ? `${contextEvidenceCount} evidence records` : "Context evidence retained"}{contextQuality !== null ? ` · ${contextQuality}% quality` : ""}</p><small>{contextCollectedAt ? `Collected ${ageLabel(contextCollectedAt)}` : contextMetadata.recovered ? "Recovered from durable alert and recommendation records" : `Snapshot: ${text(contextSnapshot.snapshot_id, contextMetadata.context_fingerprint, "persisted")}`}</small></article> : null}{rootCause ? <article><div><strong>Kai analysis</strong><em className="is-inferred">INFERRED</em></div><p>Updated {ageLabel(updatedTimestamp)}</p><small>Inference is visually separated from telemetry.</small></article> : null}<button type="button" onClick={() => incidents.openTechnical(row, "evidence")}><History aria-hidden="true" /> Inspect all technical evidence</button></section>
        <section className="ic-control"><header><PauseCircle aria-hidden="true" /><div><span>Human control</span><h3>Stay in command</h3></div></header><p>{executionReady ? "Holding, taking control, or rolling back requires an authoritative execution capability." : executionUnavailableReason}</p><button type="button" disabled={!executionReady} title={!executionReady ? executionUnavailableReason : undefined} onClick={() => incidents.openTechnical(row, "resolution")}><Gauge aria-hidden="true" /> {executionReady ? "Take control in governed workspace" : "No execution to control"}</button><button type="button" disabled title="Available only when the backend reports an active, controllable execution"><RotateCcw aria-hidden="true" /> Rollback unavailable</button></section>
      </aside>
    </div>

    <footer className="ic-truth-note"><ShieldCheck aria-hidden="true" /><span><strong>Operational truth policy:</strong> unavailable backend fields stay unavailable. KaiMS does not invent confidence, execution progress, safety controls, or recovery results.</span><button type="button" onClick={() => { incidents.refresh(); setDirectRequestVersion((version) => version + 1); }}><RefreshCw aria-hidden="true" /> Refresh incident</button></footer>
  </article>;
}
