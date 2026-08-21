import { FileClock, RefreshCw, ShieldCheck, ShieldX } from "lucide-react";

import { useRouteRuntime } from "../../app/routeRuntime";

const formatTime = (value?: string) => value
  ? `${new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST`
  : "-";

export function GatewaySafetyView({ mode = "safety" }: { mode?: "safety" | "audit" }) {
  const { safety } = useRouteRuntime();
  const isAudit = mode === "audit";
  const latestTrace = safety.summary.latest_trace_id || "No trace recorded";

  return (
    <section className={`grid single-col operational-route governance-workspace is-${mode}`}>
      <section className="route-insight-strip" aria-label={isAudit ? "Audit event summary" : "Gateway safety summary"}>
        <article><FileClock aria-hidden="true" /><span><small>Recorded events</small><strong>{safety.summary.total_events || 0}</strong></span></article>
        <article><ShieldCheck aria-hidden="true" /><span><small>Allowed</small><strong>{safety.summary.allowed || 0}</strong></span></article>
        <article><ShieldX aria-hidden="true" /><span><small>Blocked</small><strong>{safety.summary.blocked || 0}</strong></span></article>
        <article><span className="route-insight-mark">?</span><span><small>Needs review</small><strong>{safety.summary.review || 0}</strong></span></article>
      </section>

      <article className="panel route-data-panel">
        <div className="panel-head">
          <div><span className="discovery-eyebrow">{isAudit ? "Governance evidence" : "Execution guardrails"}</span><h2>{isAudit ? "Policy decision audit trail" : "Gateway safety decisions"}</h2><p>{isAudit ? "Reconstruct policy outcomes with their trace, HTTP response, latency, score, and recorded reason." : "Review the policy decision and its reasons at the boundary before an operational change is accepted."}</p></div>
          <button className="button-secondary" type="button" onClick={safety.refresh}><RefreshCw size={15} aria-hidden="true" /> Refresh evidence</button>
        </div>
        {safety.summaryError ? <p className="error" role="alert">{safety.summaryError}</p> : null}
        <div className="route-trace-banner"><span>Latest trace</span><code>{latestTrace}</code></div>
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Recent governed gateway decisions</caption>
            <thead><tr><th>Path</th><th>HTTP status</th><th>Decision</th><th>Risk score</th><th>Latency</th><th>Recorded reasons</th></tr></thead>
            <tbody>
              {safety.events.map((row, index) => <tr key={`${row.trace_id || "gw"}-${index}`}><td><code>{row.path || "-"}</code></td><td>{row.status_code || "-"}</td><td><span className={`pill status-${String(row.safety?.decision || "unknown").toLowerCase()}`}>{row.safety?.decision || "-"}</span></td><td>{row.safety?.score ?? "-"}</td><td>{row.latency_ms ? `${row.latency_ms} ms` : "-"}</td><td>{Array.isArray(row.safety?.reasons) && row.safety.reasons.length ? row.safety.reasons.join("; ") : "No policy reason recorded"}</td></tr>)}
              {!safety.events.length ? <tr><td colSpan={6}><div className="table-empty-state"><ShieldCheck aria-hidden="true" /><strong>No gateway decisions in scope</strong><span>Policy evidence appears after traffic crosses the governed gateway.</span></div></td></tr> : null}
            </tbody>
          </table>
        </div>
      </article>

      <article className="panel route-data-panel">
        <div className="panel-head"><div><span className="discovery-eyebrow">Source evidence</span><h3>Realtime landing-pad ingestion</h3><p>Confirm which source alert entered the platform and when it was accepted.</p></div></div>
        {safety.landingError ? <p className="error" role="alert">{safety.landingError}</p> : null}
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Realtime alert landing-pad records</caption>
            <thead><tr><th>Received at</th><th>Alert</th><th>Service</th><th>Severity</th><th>Status</th><th>Source file</th></tr></thead>
            <tbody>
              {safety.landingRows.map((row, index) => <tr key={`${row.file || "landing-pad"}-${index}`}><td>{formatTime(row.received_at || row.modified_at)}</td><td><strong>{row.name || row.alertname || "-"}</strong></td><td>{row.service || "-"}</td><td><span className={`pill severity-${String(row.severity || "unknown").toLowerCase()}`}>{String(row.severity || "-").toUpperCase()}</span></td><td>{row.alert_status || "-"}</td><td><code>{row.file || "-"}</code></td></tr>)}
              {!safety.landingRows.length ? <tr><td colSpan={6}><div className="table-empty-state"><FileClock aria-hidden="true" /><strong>No landing-pad records in scope</strong><span>New source intake will appear here as it is accepted.</span></div></td></tr> : null}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  );
}
