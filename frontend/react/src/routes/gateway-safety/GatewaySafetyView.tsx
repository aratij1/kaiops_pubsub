import { AlertTriangle, FileClock, LockKeyhole, RefreshCw, ShieldCheck, ShieldX, Siren, Workflow } from "lucide-react";

import { useRouteRuntime } from "../../app/routeRuntime";
import "./GatewaySafetyView.css";

const formatTime = (value?: string) => value
  ? `${new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST`
  : "-";

export function GatewaySafetyView({ mode = "safety" }: { mode?: "safety" | "audit" }) {
  const { safety } = useRouteRuntime();
  const isAudit = mode === "audit";
  const latestTrace = safety.summary.latest_trace_id || "No trace recorded";

  if (!isAudit) {
    const summary = safety.summary || {};
    return (
      <section className="trust-center">
        <header className="tc-hero">
          <span className="tc-hero-icon"><ShieldCheck aria-hidden="true" /></span>
          <div><span>Governed automation</span><h2>Trust Center</h2><p>Live policy decisions, execution guardrails, and operator control for every automated action.</p></div>
          <button type="button" onClick={safety.refresh}><RefreshCw aria-hidden="true" /> Refresh trust data</button>
        </header>

        {safety.summaryError ? <section className="tc-degraded" role="alert"><AlertTriangle aria-hidden="true" /><div><strong>Trust telemetry is partially unavailable</strong><p>Recorded policy evidence could not be refreshed. Existing guardrails remain enforced and high-impact controls stay unavailable.</p></div></section> : null}

        <div className="tc-layout">
          <main>
            <section className="tc-section">
              <header><div><span>Decision posture</span><h3>Observed gateway outcomes</h3></div><small>Backend-recorded evidence only</small></header>
              <div className="tc-stats">
                <article><small>Recorded</small><strong>{summary.total_events || 0}</strong><span>Policy decisions</span></article>
                <article><small>Allowed</small><strong>{summary.allowed || 0}</strong><span>Within guardrails</span></article>
                <article><small>Review</small><strong>{summary.review || 0}</strong><span>Human decision required</span></article>
                <article><small>Blocked</small><strong>{summary.blocked || 0}</strong><span>Prevented by policy</span></article>
              </div>
            </section>

            <section className="tc-section">
              <header><div><span>Evidence stream</span><h3>Recent governed decisions</h3></div><Workflow aria-hidden="true" /></header>
              <div className="tc-event-list">
                {safety.events.map((row, index) => <article key={`${row.trace_id || "event"}-${index}`}><span className="tc-event-icon"><LockKeyhole aria-hidden="true" /></span><span><small>{row.path || "Governed request"}</small><strong>{row.safety?.decision || "Decision unavailable"}</strong></span><span className={`pill status-${String(row.safety?.decision || "unknown").toLowerCase()}`}>{row.status_code || "—"}</span><span><small>Risk score</small><strong>{row.safety?.score ?? "—"}</strong></span><p>{row.safety?.reasons?.join("; ") || `Trace ${row.trace_id || "not recorded"}`}</p></article>)}
                {!safety.events.length ? <div className="tc-empty"><ShieldCheck aria-hidden="true" /><span><strong>No governed decisions in scope</strong><small>New backend policy decisions will appear here.</small></span></div> : null}
              </div>
            </section>
          </main>

          <aside>
            <section className="tc-section">
              <header><div><span>Autonomy mode</span><h3>Policy managed</h3></div><LockKeyhole aria-hidden="true" /></header>
              <div className="tc-mode"><small>Current posture</small><strong>{safety.summaryError ? "Telemetry degraded" : "Guardrails active"}</strong><p>Execution authority remains with backend policy. The interface never infers or elevates automation capability.</p></div>
              <div className="tc-mode-list"><button type="button" disabled><span>Observe</span><small>Recorded state</small></button><button type="button" disabled><span>Human gate</span><small>Approval required</small></button></div>
              <button className="tc-emergency" type="button" disabled><Siren aria-hidden="true" /> Emergency stop unavailable</button>
            </section>
            <section className="tc-section tc-guardrails">
              <header><div><span>Guardrail status</span><h3>Control guarantees</h3></div><ShieldCheck aria-hidden="true" /></header>
              <dl><div><dt>Policy enforcement</dt><dd>Backend</dd></div><div><dt>Audit trail</dt><dd>Immutable</dd></div><div><dt>Human approval</dt><dd>Required by risk</dd></div><div><dt>Telemetry</dt><dd>{safety.summaryError ? "Degraded" : "Available"}</dd></div></dl>
            </section>
          </aside>
        </div>
      </section>
    );
  }

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
