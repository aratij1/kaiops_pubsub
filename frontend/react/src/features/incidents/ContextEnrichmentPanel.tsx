import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CircleAlert, CircleCheck, RefreshCw, UserRound } from "lucide-react";
import { fetchJson, formatUtcTimestamp } from "../../appHelpers.jsx";

export type EvidenceGap = { category: string; reason?: string };
type Job = { connector_id: string; status: string; attempt?: number; last_error_code?: string | null; last_error?: string | null };
type HumanRequest = { request_id: string; expected_responder?: string | null; due_at?: string | null; status: string; assignment_failure_reason?: string | null };
type Requirement = { requirement_id: string; rca_version?: number | null; category: string; question: string; status: string; created_at?: string | null; updated_at?: string | null; evidence_ids?: string[]; latest_job?: Job | null; active_human_request?: HumanRequest | null };
type OperationsState = {
  schema_version: "kaiops.operations-state.v1"; lifecycle_state: string; updated_at?: string | null;
  context?: { snapshot_id?: string | null; version?: number; evidence_ids?: string[] };
  investigation?: { rca_version?: number; snapshot_id?: string | null };
  requirements?: Requirement[]; requirement_history?: Requirement[];
};

const TERMINAL_STATES = new Set(["CLOSED"]);

function friendlyFailure(error: unknown) {
  const message = String((error as Error)?.message || error || "");
  if (/HTTP 404/.test(message)) return "Incident operations are unavailable for this release. Confirm the UI, gateway, and context service use the same version.";
  if (/HTTP 401|HTTP 403/.test(message)) return "Your session is not authorized to view this incident's evidence lifecycle.";
  if (/HTTP 502|HTTP 503|HTTP 504|network|fetch/i.test(message)) return "Incident operations are temporarily unavailable. KaiMS will retry automatically.";
  return "Incident operations could not be loaded. Retry or contact the platform owner if the problem continues.";
}

function lifecycleLabel(state: string) {
  const labels: Record<string, string> = { DETECTED: "No evidence yet", REQUIREMENTS_IDENTIFIED: "Evidence required", COLLECTING: "Collecting", WAITING_FOR_HUMAN: "Waiting for human", COLLECTION_BLOCKED: "Blocked", INVESTIGATION_FAILED: "Failed", CONTEXT_READY: "Context ready", INVESTIGATING: "Investigating", RCA_READY: "RCA ready", CLOSED: "Closed" };
  return labels[state] || state.replaceAll("_", " ").toLowerCase();
}

function actionableFailure(item: Requirement) {
  if (item.active_human_request?.status === "assignment_blocked") return "No authorized responder could be resolved. Assign an incident or service owner.";
  if (item.active_human_request?.assignment_failure_reason) return "Human evidence assignment needs attention.";
  if (item.latest_job?.last_error_code) return `Collection failed (${item.latest_job.last_error_code}). Review connector configuration and retry.`;
  if (item.latest_job?.last_error) return "The connector could not collect this evidence. Review connector health and retry.";
  return "";
}

export type ContextEnrichmentPanelProps = { incidentId: string; alertId?: string; accessToken: string; declaredGaps: EvidenceGap[]; onIncidentRefresh: () => Promise<void> };

export default function ContextEnrichmentPanel({ incidentId, alertId, accessToken, declaredGaps, onIncidentRefresh }: ContextEnrichmentPanelProps) {
  const [state, setState] = useState<OperationsState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [references, setReferences] = useState<Record<string, string>>({});
  const [announcement, setAnnouncement] = useState("");
  const inFlight = useRef(false);
  const previousState = useRef("");
  const failureCount = useRef(0);
  const headers = useMemo(() => ({ Authorization: `Bearer ${accessToken}` }), [accessToken]);

  const load = useCallback(async (manual = false) => {
    if (!incidentId || !accessToken || inFlight.current) return;
    inFlight.current = true;
    if (manual) setLoading(true);
    try {
      const result = await fetchJson(`/api-gateway/incidents/${encodeURIComponent(incidentId)}/operations-state`, { headers, maxAttempts: 1, staleTimeMs: 0 }) as OperationsState;
      setState(result); setError(""); failureCount.current = 0;
      if (previousState.current && previousState.current !== result.lifecycle_state) {
        setAnnouncement(`Evidence lifecycle changed to ${lifecycleLabel(result.lifecycle_state)}.`);
        void onIncidentRefresh();
      }
      previousState.current = result.lifecycle_state;
    } catch (reason) { failureCount.current += 1; setError(friendlyFailure(reason)); }
    finally { inFlight.current = false; setLoading(false); }
  }, [accessToken, headers, incidentId, onIncidentRefresh]);

  useEffect(() => {
    let cancelled = false; let timer: number | undefined;
    previousState.current = ""; failureCount.current = 0;
    const poll = async () => {
      if (cancelled) return;
      if (!document.hidden) await load(false);
      if (cancelled || TERMINAL_STATES.has(previousState.current)) return;
      timer = window.setTimeout(() => void poll(), Math.min(3000 * (2 ** failureCount.current), 30_000));
    };
    void poll();
    const resume = () => { if (!document.hidden && !inFlight.current) void load(false); };
    document.addEventListener("visibilitychange", resume);
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); document.removeEventListener("visibilitychange", resume); };
  }, [incidentId, load]);

  const submit = async (requirementId: string) => {
    const response = String(answers[requirementId] || "").trim();
    const sourceReference = String(references[requirementId] || "").trim();
    if (!response || !sourceReference) return;
    setLoading(true); setError("");
    try {
      await fetchJson(`/api-gateway/incidents/${encodeURIComponent(incidentId)}/context-gaps/${encodeURIComponent(requirementId)}/responses`, { method: "POST", headers, body: JSON.stringify({ response, source_reference: sourceReference }) });
      setAnswers((current) => ({ ...current, [requirementId]: "" }));
      setReferences((current) => ({ ...current, [requirementId]: "" }));
      setAnnouncement("Human evidence was accepted. KaiMS will publish a new governed context snapshot and analysis.");
      await load(true);
    } catch (reason) { setError(friendlyFailure(reason)); setLoading(false); }
  };

  const current = state?.requirements || [];
  const history = state?.requirement_history || [];
  const rcaVersion = state?.investigation?.rca_version || 0;
  const evidenceIds = state?.context?.evidence_ids || [];

  const card = (item: Requirement, historical = false) => {
    const request = item.active_human_request; const job = item.latest_job;
    const complete = ["collected", "answered", "satisfied"].includes(item.status.toLowerCase());
    const status = request?.status || job?.status || item.status; const failure = actionableFailure(item);
    const recordedAt = item.updated_at || item.created_at;
    return <article key={item.requirement_id} className={historical ? "is-historical" : undefined}>
      <div className="context-enrichment-item-heading">
        {complete ? <CircleCheck size={17} /> : request ? <UserRound size={17} /> : <RefreshCw size={17} />}
        <div><strong>{item.category.replaceAll("_", " ")}</strong><p>{item.question}</p><small className="context-enrichment-version">{item.rca_version == null ? "RCA version unavailable" : `RCA v${item.rca_version}`}{recordedAt ? ` · updated ${formatUtcTimestamp(recordedAt)}` : ""}</small></div>
        <span>{status.replaceAll("_", " ")}</span>
      </div>
      {job ? <small>Latest attempt {job.attempt || 1} · connector {job.connector_id} · {job.status.replaceAll("_", " ")}</small> : null}
      {item.evidence_ids?.length ? <small className="context-enrichment-evidence">Accepted evidence ({item.evidence_ids.length}): {item.evidence_ids.join(", ")}</small> : null}
      {failure ? <p className="context-enrichment-action" role="status">{failure}</p> : null}
      {!historical && request?.status === "pending" ? <div className="context-enrichment-response">
        <small>Assigned to {request.expected_responder || "an authorized responder"}{request.due_at ? ` · due ${formatUtcTimestamp(request.due_at)}` : ""}</small>
        <textarea aria-label={`Response for ${item.category}`} value={answers[item.requirement_id] || ""} onChange={(event) => setAnswers((value) => ({ ...value, [item.requirement_id]: event.target.value }))} placeholder="Provide the factual observation." />
        <input aria-label={`Source reference for ${item.category}`} value={references[item.requirement_id] || ""} onChange={(event) => setReferences((value) => ({ ...value, [item.requirement_id]: event.target.value }))} placeholder="Source reference (ticket, dashboard, or catalog URL)" />
        <button type="button" className="button-primary" disabled={loading || !String(answers[item.requirement_id] || "").trim() || !String(references[item.requirement_id] || "").trim()} onClick={() => void submit(item.requirement_id)}>Submit evidence</button>
      </div> : null}
    </article>;
  };

  return <section className="context-enrichment-panel" aria-labelledby="context-enrichment-title">
    <div className="sr-only" aria-live="polite">{announcement}</div>
    <header><div><span className="discovery-eyebrow">Autonomous context enrichment</span><h3 id="context-enrichment-title">Evidence gaps and human requests</h3><p>KaiMS keeps collecting governed evidence while this investigation remains open.</p></div><button type="button" className="button-secondary" onClick={() => void load(true)} disabled={loading}><RefreshCw size={15} className={loading ? "is-spinning" : ""} /> Refresh</button></header>
    {state ? <div className="context-enrichment-summary" role="status"><strong>{lifecycleLabel(state.lifecycle_state)}</strong><span>Last updated {state.updated_at ? formatUtcTimestamp(state.updated_at) : "unavailable"}</span><span>Snapshot {state.context?.snapshot_id ? `v${state.context.version} · ${state.context.snapshot_id}` : "not published"}</span><span>RCA {rcaVersion ? `v${rcaVersion}` : "not published"} · {evidenceIds.length} accepted evidence record{evidenceIds.length === 1 ? "" : "s"}</span></div> : null}
    {error ? <p className="context-enrichment-error" role="alert"><CircleAlert size={17} />{error}</p> : null}
    {!alertId && declaredGaps.length ? <p className="context-enrichment-error" role="status"><CircleAlert size={17} />Canonical alert binding is missing. Backend orchestration will regenerate analysis after a governed snapshot is committed.</p> : null}
    {!error && state && !current.length ? <p className="context-enrichment-empty">{declaredGaps.length ? "Evidence requirements have not been projected yet. KaiMS will continue monitoring this incident." : "No unresolved evidence gaps are declared."}</p> : null}
    {current.length ? <section className="context-enrichment-current" aria-labelledby="current-evidence-title"><div className="context-enrichment-group-heading"><div><span>Active evidence work</span><h4 id="current-evidence-title">{rcaVersion ? `Current RCA · v${rcaVersion}` : "Current investigation"}</h4></div><small>{current.length} requirement{current.length === 1 ? "" : "s"}</small></div><div className="context-enrichment-list">{current.map((item) => card(item))}</div></section> : null}
    {history.length ? <details className="context-enrichment-history"><summary>Previous RCA versions <span>{history.length} archived requirement{history.length === 1 ? "" : "s"}</span></summary><p>Retained for audit history. Responses can only be submitted against active backend-projected work.</p><div className="context-enrichment-list">{history.map((item) => card(item, true))}</div></details> : null}
  </section>;
}
