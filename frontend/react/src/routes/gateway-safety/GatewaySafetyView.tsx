import { AlertTriangle, LockKeyhole, RefreshCw, ShieldCheck, Siren, Workflow } from "lucide-react";

import { useRouteRuntime } from "../../app/routeRuntime";
import "./GatewaySafetyView.css";

export function GatewaySafetyView() {
  const { safety } = useRouteRuntime();
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
