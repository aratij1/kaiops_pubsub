import { AlertTriangle, CheckCircle2, Clock3, RefreshCw, ShieldCheck, ShieldOff, SlidersHorizontal } from "lucide-react";

import { useRouteRuntimeSlice } from "../../app/routeRuntime";
import { EvidenceBadge, StatusBadge } from "../../components/design-system";
import "./GatewaySafetyView.css";

const formatTime = (value?: string) => value ? `${new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST` : "Unavailable";

export function GatewaySafetyView() {
  const safety = useRouteRuntimeSlice("safety");
  const total = Number(safety.summary.total_events || 0);
  const allowed = Number(safety.summary.allowed || 0);
  const review = Number(safety.summary.review || 0);
  const blocked = Number(safety.summary.blocked || 0);
  const latest = safety.events[0];
  const degraded = Boolean(safety.summaryError || safety.landingError);

  return <section className="trust-center">
    <header className="tc-hero"><div className="tc-hero-icon"><ShieldCheck aria-hidden="true" /></div><div><span>AI Trust</span><h2>Automation governance operators can understand</h2><p>Observed gateway decisions, safety outcomes, and evidence freshness. Backend policy remains authoritative.</p></div><button type="button" onClick={safety.refresh}><RefreshCw aria-hidden="true" /> Refresh trust data</button></header>

    {degraded ? <section className="tc-degraded" role="status"><AlertTriangle aria-hidden="true" /><div><strong>Trust telemetry is partially unavailable</strong><p>{safety.summaryError || safety.landingError}. Mutable controls remain unavailable until authoritative state can be verified.</p></div></section> : null}

    <div className="tc-layout"><main>
      <section className="tc-section"><header><div><span>Decision outcomes</span><h3>Gateway policy activity</h3></div><EvidenceBadge provenance={latest?.created_at ? "RECENT" : "UNAVAILABLE"} /></header><div className="tc-stats"><article><small>Evaluated</small><strong>{total}</strong><span>Gateway events</span></article><article><small>Allowed</small><strong>{allowed}</strong><span>{total ? `${Math.round(allowed / total * 100)}% of observed` : "No observed events"}</span></article><article><small>Human review</small><strong>{review}</strong><span>Policy escalations</span></article><article><small>Blocked</small><strong>{blocked}</strong><span>Safety stops</span></article></div></section>

      <section className="tc-section"><header><div><span>Recent autonomous and governed actions</span><h3>Decision audit</h3></div><small>Latest trace: {safety.summary.latest_trace_id || "Unavailable"}</small></header><div className="tc-event-list">{safety.events.length ? safety.events.slice(0, 20).map((row, index) => { const decision = String(row.safety?.decision || "unavailable").toLowerCase(); const tone = decision.includes("block") ? "critical" : decision.includes("review") ? "warning" : decision.includes("allow") ? "success" : "inactive"; return <article key={`${row.trace_id || "gateway"}-${index}`}><span className="tc-event-icon">{tone === "critical" ? <ShieldOff aria-hidden="true" /> : tone === "success" ? <CheckCircle2 aria-hidden="true" /> : <Clock3 aria-hidden="true" />}</span><span><strong>{row.path || "Gateway action"}</strong><small>{formatTime(row.created_at)} · Trace {row.trace_id || "unavailable"}</small></span><StatusBadge tone={tone}>{decision}</StatusBadge><span><small>Trust score</small><strong>{row.safety?.score ?? "—"}</strong></span><p>{Array.isArray(row.safety?.reasons) && row.safety.reasons.length ? row.safety.reasons.join("; ") : "No policy reason was published."}</p></article>; }) : <div className="tc-empty"><ShieldCheck aria-hidden="true" /><span><strong>No gateway decisions returned</strong><small>Trust activity will appear when the safety API reports an event.</small></span></div>}</div></section>
    </main><aside>
      <section className="tc-section tc-autonomy"><header><div><span>Autonomy control</span><h3>Current mode</h3></div><SlidersHorizontal aria-hidden="true" /></header><div className="tc-mode"><small>Authoritative mode</small><strong>Unavailable from safety API</strong><p>KaiMS will not infer a mutable autonomy mode from decision counts.</p></div><div className="tc-mode-list">{["Observe", "Assist", "Guided", "Autonomous"].map((mode) => <button type="button" key={mode} disabled title="An authenticated autonomy policy API is required"><span>{mode}</span><small>Policy API required</small></button>)}</div><button className="tc-emergency" type="button" disabled title="Emergency stop is unavailable without an authoritative control endpoint"><ShieldOff aria-hidden="true" /> Emergency stop unavailable</button></section>
      <section className="tc-section tc-guardrails"><header><div><span>Trust indicators</span><h3>Observed safeguards</h3></div></header><dl><div><dt>Blocked actions</dt><dd>{blocked}</dd></div><div><dt>Human-review decisions</dt><dd>{review}</dd></div><div><dt>Latest policy decision</dt><dd>{latest?.safety?.decision || "Unavailable"}</dd></div><div><dt>Latest evidence</dt><dd>{formatTime(latest?.created_at)}</dd></div><div><dt>Landing-pad signals</dt><dd>{safety.landingRows.length}</dd></div></dl></section>
    </aside></div>
  </section>;
}
