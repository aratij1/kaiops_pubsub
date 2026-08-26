import { CheckCircle2, Clock3, FileSearch, RefreshCw, ScrollText, ShieldAlert } from "lucide-react";

import { useRouteRuntimeSlice } from "../../app/routeRuntime";
import { StatusBadge } from "../../components/design-system";
import "./AuditRoute.css";

const formatTime = (value?: string) => value
  ? `${new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST`
  : "Unavailable";

export default function AuditRoute() {
  const audit = useRouteRuntimeSlice("safety");
  const rows = audit.events;
  const uniqueTraces = new Set(rows.map((row) => row.trace_id).filter(Boolean)).size;
  const failedRequests = rows.filter((row) => Number(row.status_code || 0) >= 400).length;

  return <section className="audit-workspace">
    <header className="audit-hero"><div className="audit-hero-icon"><ScrollText aria-hidden="true" /></div><div><span>Governance record</span><h2>Audit trail</h2><p>Chronological, immutable-facing records of gateway requests and policy decisions for investigation and compliance review.</p></div><button type="button" onClick={audit.refresh}><RefreshCw aria-hidden="true" /> Refresh records</button></header>

    {audit.summaryError ? <div className="audit-warning" role="status"><ShieldAlert aria-hidden="true" /><span><strong>Audit summary is partially unavailable</strong><small>{audit.summaryError}</small></span></div> : null}

    <section className="audit-metrics" aria-label="Audit summary"><article><FileSearch /><span><strong>{rows.length}</strong><small>records loaded</small></span></article><article><Clock3 /><span><strong>{uniqueTraces}</strong><small>unique traces</small></span></article><article><CheckCircle2 /><span><strong>{Number(audit.summary.allowed || 0)}</strong><small>allowed decisions</small></span></article><article><ShieldAlert /><span><strong>{failedRequests}</strong><small>HTTP failures</small></span></article></section>

    <article className="audit-ledger"><header><div><span>Event ledger</span><h3>Recorded gateway activity</h3></div><small>Latest trace: {audit.summary.latest_trace_id || "Unavailable"}</small></header><div className="table-wrap"><table><thead><tr><th>Time</th><th>Request path</th><th>HTTP</th><th>Policy decision</th><th>Score</th><th>Trace ID</th></tr></thead><tbody>{rows.map((row, index) => { const decision = String(row.safety?.decision || "unavailable").toLowerCase(); const tone = decision.includes("block") ? "critical" : decision.includes("review") ? "warning" : decision.includes("allow") ? "success" : "inactive"; return <tr key={`${row.id || row.trace_id || "audit"}-${index}`}><td>{formatTime(row.created_at)}</td><td><code>{row.path || "-"}</code></td><td>{row.status_code ?? "-"}</td><td><StatusBadge tone={tone}>{decision}</StatusBadge></td><td>{row.safety?.score ?? "-"}</td><td><code>{row.trace_id || "-"}</code></td></tr>; })}{!rows.length ? <tr><td colSpan={6}><div className="audit-empty"><ScrollText /><span><strong>No audit records returned</strong><small>Gateway activity will appear here after requests are evaluated.</small></span></div></td></tr> : null}</tbody></table></div></article>
  </section>;
}
