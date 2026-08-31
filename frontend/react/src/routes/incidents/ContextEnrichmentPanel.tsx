import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleAlert, CircleCheck, RefreshCw, UserRound } from "lucide-react";
import { fetchJson, formatUtcTimestamp } from "../../appHelpers.jsx";

export type EvidenceGap = { category: string; reason?: string };

type Requirement = {
  requirement_id: string;
  category: string;
  question: string;
  reason: string;
  status: string;
  candidate_connectors?: string[];
  assigned_to?: string | null;
};

type Activity = {
  requirements?: Requirement[];
  jobs?: Array<{ requirement_id: string; connector_id: string; status: string; last_error?: string }>;
  human_requests?: Array<{
    request_id: string; requirement_id: string; expected_responder: string;
    due_at: string; status: string;
  }>;
};

function friendlyFailure(error: unknown) {
  const message = String((error as Error)?.message || error || "");
  if (/HTTP 404/.test(message)) {
    return "Context enrichment API is missing from the deployed backend. Deploy the UI, gateway, and context-agent from the same release.";
  }
  return message.replace(/^HTTP \d+:\s*/, "") || "Context enrichment is temporarily unavailable.";
}

export type ContextEnrichmentPanelProps = {
  incidentId: string;
  alertId?: string;
  accessToken: string;
  declaredGaps: EvidenceGap[];
  onIncidentRefresh: () => Promise<void>;
  onFreshAnalysisRequested: () => Promise<void>;
};

export default function ContextEnrichmentPanel({
  incidentId, alertId, accessToken, declaredGaps, onIncidentRefresh, onFreshAnalysisRequested,
}: ContextEnrichmentPanelProps) {
  const [activity, setActivity] = useState<Activity>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const headers = useMemo(() => ({ Authorization: `Bearer ${accessToken}` }), [accessToken]);

  const load = useCallback(async () => {
    if (!incidentId || !accessToken) return;
    setLoading(true);
    setError("");
    try {
      const result = await fetchJson(`/api-gateway/incidents/${encodeURIComponent(incidentId)}/context-gaps`, {
        headers, maxAttempts: 1, staleTimeMs: 0,
      });
      setActivity(result || {});
    } catch (reason) {
      setError(friendlyFailure(reason));
    } finally {
      setLoading(false);
    }
  }, [accessToken, headers, incidentId]);

  useEffect(() => { void load(); }, [load]);

  const submit = async (requirementId: string) => {
    const response = String(answers[requirementId] || "").trim();
    if (!response) return;
    setLoading(true);
    setError("");
    try {
      await fetchJson(
        `/api-gateway/incidents/${encodeURIComponent(incidentId)}/context-gaps/${encodeURIComponent(requirementId)}/responses`,
        { method: "POST", headers, body: JSON.stringify({ response }) },
      );
      setAnswers((current) => ({ ...current, [requirementId]: "" }));
      await load();
      await onIncidentRefresh();
      if (alertId) await onFreshAnalysisRequested();
    } catch (reason) {
      setError(friendlyFailure(reason));
      setLoading(false);
    }
  };

  const requirements = activity.requirements || [];
  const jobs = activity.jobs || [];
  const humanRequests = activity.human_requests || [];
  return <section className="context-enrichment-panel" aria-labelledby="context-enrichment-title">
    <header>
      <div><span className="discovery-eyebrow">Autonomous context enrichment</span>
        <h3 id="context-enrichment-title">Evidence gaps and human requests</h3>
        <p>KaiMS keeps collecting governed evidence while this investigation remains open.</p>
      </div>
      <button type="button" className="button-secondary" onClick={() => void load()} disabled={loading}>
        <RefreshCw size={15} className={loading ? "is-spinning" : ""} /> Refresh
      </button>
    </header>
    {error ? <p className="context-enrichment-error" role="alert"><CircleAlert size={17} />{error}</p> : null}
    {!alertId && declaredGaps.length ? <p className="context-enrichment-error" role="status"><CircleAlert size={17} />Canonical alert binding is missing. Evidence activity remains visible, but fresh RCA regeneration is disabled.</p> : null}
    {!error && requirements.length === 0 ? <p className="context-enrichment-empty">
      {declaredGaps.length ? "The RCA declared gaps but no durable work items were created. Run a fresh analysis after deploying the matching backend release." : "No unresolved evidence gaps are declared."}
    </p> : null}
    <div className="context-enrichment-list">
      {requirements.map((item) => {
        const job = jobs.find((row) => row.requirement_id === item.requirement_id);
        const request = humanRequests.find((row) => row.requirement_id === item.requirement_id);
        const complete = ["collected", "answered"].includes(item.status);
        return <article key={item.requirement_id}>
          <div className="context-enrichment-item-heading">
            {complete ? <CircleCheck size={17} /> : request ? <UserRound size={17} /> : <RefreshCw size={17} />}
            <div><strong>{item.category.replaceAll("_", " ")}</strong><p>{item.question}</p></div>
            <span>{job?.status || request?.status || item.status}</span>
          </div>
          {job ? <small>Connector: {job.connector_id}{job.last_error ? ` · ${job.last_error}` : ""}</small> : null}
          {request && request.status === "pending" ? <div className="context-enrichment-response">
            <small>Assigned to {request.expected_responder} · due {formatUtcTimestamp(request.due_at)}</small>
            <textarea aria-label={`Response for ${item.category}`} value={answers[item.requirement_id] || ""}
              onChange={(event) => setAnswers((current) => ({ ...current, [item.requirement_id]: event.target.value }))}
              placeholder="Provide the factual observation and source reference." />
            <button type="button" className="button-primary" disabled={loading || !String(answers[item.requirement_id] || "").trim()}
              onClick={() => void submit(item.requirement_id)}>Submit evidence</button>
          </div> : null}
        </article>;
      })}
    </div>
  </section>;
}
