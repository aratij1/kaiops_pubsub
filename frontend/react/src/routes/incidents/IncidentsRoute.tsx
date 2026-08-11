import { useEffect, useMemo, useState } from "react";
import { useRouteRuntimeSlice, type IncidentFilters } from "../../app/routeRuntime";
import "./IncidentsRoute.css";
// Load after route CSS so modern layout overrides win on this page.
import "../../styles/modern-layout-overrides.css";
import "../../custom.css";
import { OperationsWorkflowNav } from "../../components/operations/OperationsWorkflowNav";

const PAGE_SIZE = 15;
export default function IncidentsRoute() {
  const incidents = useRouteRuntimeSlice("incidents");
  const [page, setPage] = useState(1);
  const pages = Math.max(1, Math.ceil(incidents.rows.length / PAGE_SIZE));
  useEffect(() => setPage((current) => Math.min(current, pages)), [pages]);
  useEffect(() => setPage(1), [incidents.filters.risk_tier, incidents.filters.execution_mode, incidents.filters.status, incidents.filters.service]);
  // #region agent log
  useEffect(() => {
    const root = document.documentElement;
    const td = document.querySelector(".operations-center .contained-table td:nth-child(2)");
    const code = document.querySelector(".operations-center .contained-table code");
    const pill = document.querySelector(".operations-center .contained-table .pill");
    const table = document.querySelector(".operations-center .contained-table");
    if (!td || !table) return;
    const tdCs = getComputedStyle(td);
    const tableCs = getComputedStyle(table);
    const codeCs = code ? getComputedStyle(code) : null;
    const pillCs = pill ? getComputedStyle(pill) : null;
    fetch("http://127.0.0.1:7875/ingest/ccf9f1e5-f5b0-448c-9300-44f1d9b7446d", { method: "POST", headers: { "Content-Type": "application/json", "X-Debug-Session-Id": "fe716a" }, body: JSON.stringify({ sessionId: "fe716a", runId: "contrast-post", hypothesisId: "A", location: "IncidentsRoute.tsx:contrast", message: "Incidents table computed contrast", data: { uiTheme: root.getAttribute("data-ui-theme"), hasDarkClass: root.classList.contains("dm-theme-dark"), hasLightClass: root.classList.contains("dm-theme-light"), ink: getComputedStyle(root).getPropertyValue("--ink").trim(), tdColor: tdCs.color, tdBg: tdCs.backgroundColor, tableBg: tableCs.backgroundColor, codeColor: codeCs?.color || null, pillColor: pillCs?.color || null, pillBg: pillCs?.backgroundColor || null }, timestamp: Date.now() }) }).catch(() => {});
  }, [incidents.rows.length, page]);
  // #endregion
  const rows = useMemo(() => incidents.rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), [incidents.rows, page]);
  const select = (label: string, name: keyof IncidentFilters, options: string[]) => <label>{label}<select value={incidents.filters[name]} onChange={(event) => incidents.updateFilter(name, event.target.value)}>{options.map((option) => <option value={option} key={option}>{option}</option>)}</select></label>;
  const priority = incidents.rows.filter((row) => ["high", "critical"].includes(String(row.risk_tier || "").toLowerCase())).length;
  const active = incidents.rows.filter((row) => !["closed", "resolved"].includes(String(row.status || "").toLowerCase())).length;
  return <section className="grid single-col operations-center">
    <OperationsWorkflowNav active="incidents" />
    <article className="panel operations-summary"><div><span className="discovery-eyebrow">Incident operations</span><h2>Operations Center</h2><p>Prioritize active risk, open the right incident, and keep detailed metadata out of the way until needed.</p></div><div className="operations-kpis"><span><strong>{active}</strong> active</span><span><strong>{priority}</strong> priority</span><span><strong>{incidents.rows.length}</strong> total</span></div></article>
    {incidents.scopeFallback ? <div className="incident-scope-notice"><strong>No incidents are attributed to {incidents.application} yet.</strong><span>Showing all incidents because current incident records do not include application metadata.</span></div> : null}
    <article className="panel incident-list-panel"><div className="compact-filter-bar">{select("Risk", "risk_tier", ["all", "high", "medium", "low"])}{select("Mode", "execution_mode", ["all", "human-approval", "guided-auto", "auto-execute"])}{select("Status", "status", ["all", "open", "investigating", "awaiting_approval", "remediating", "validating", "closed", "failed"])}<label className="filter-grow">Find service<input value={incidents.filters.service} placeholder="Search service" onChange={(event) => incidents.updateFilter("service", event.target.value)} /></label><button className="button-secondary" onClick={incidents.refresh}>Refresh</button></div>
      {incidents.error ? <p className="error">{incidents.error}</p> : null}<div className="contained-table"><table><thead><tr><th>Incident</th><th>Service</th><th>Risk</th><th>Mode</th><th>Status</th><th></th></tr></thead><tbody>{rows.map((row, index) => <tr key={row.incident_id || row.id || index}><td><code>{row.incident_id || row.id || "-"}</code></td><td><strong>{row.service || "-"}</strong></td><td>{row.risk_tier || "-"}</td><td>{row.execution_mode || "-"}</td><td><span className={`pill status-${String(row.status || "unknown").toLowerCase()}`}>{row.status || "-"}</span></td><td><button type="button" className="button-secondary" onClick={() => incidents.open(row)}>Open cockpit</button></td></tr>)}{!rows.length && !incidents.loading ? <tr><td colSpan={6}>No incidents match this operational view.</td></tr> : null}</tbody></table></div>
      <footer className="table-pagination"><span>Showing {rows.length ? ((page - 1) * PAGE_SIZE) + 1 : 0}–{Math.min(page * PAGE_SIZE, incidents.rows.length)} of {incidents.rows.length}</span><div><button className="button-secondary" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button><span>{page} / {pages}</span><button className="button-secondary" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>Next</button></div></footer>
    </article>
  </section>;
}
