import { useRouteRuntime } from "../../app/routeRuntime";
import "./DashboardRoute.css";

export default function DashboardRoute() {
  const { dashboard, alerts } = useRouteRuntime();
  const role = dashboard.role;
  const urgent = alerts.rows.filter((row) => ["critical", "high"].includes(String(row.severity || "").toLowerCase())).slice(0, 5);

  return <section className="operations-workspace">
    <div className="operations-toolbar"><p>{role.description}</p><button type="button" className="button-secondary" onClick={() => { dashboard.refreshProjects(); alerts.refresh(); }} disabled={role.refreshing}>{role.refreshing ? "Syncing…" : "Refresh"}</button></div>

    <div className="operations-signal-strip">{role.cards.slice(0, 4).map((card) => <button type="button" className={`operations-signal is-${card.tone}`} key={card.label} disabled={!dashboard.allowedTabs.includes(card.tab)} onClick={() => dashboard.openSection(card.tab)}><span>{card.label}</span><strong>{card.value}</strong><small>{card.detail}</small></button>)}</div>

    <div className="operations-main-grid"><article className="panel operations-alert-board"><header><div><span className="discovery-eyebrow">Priority queue</span><h3>Alerts needing attention</h3></div><button type="button" className="button-secondary" onClick={() => dashboard.openSection("stream")}>Open alert stream</button></header>{alerts.loading ? <div className="operations-loading">Updating operational signals…</div> : urgent.length ? <div className="operations-alert-list">{urgent.map((row, index) => <button type="button" key={`${row.id || row.file || row.name}-${index}`} onClick={() => alerts.open(row)}><i className={`severity-dot is-${String(row.severity || "warning").toLowerCase()}`} /><span><strong>{row.name || row.alert_name || "Unnamed alert"}</strong><small>{row.application || row.project_name || row.project || row.service || "Unscoped application"}</small></span><b>{String(row.severity || "warning").toUpperCase()}</b><em>Open →</em></button>)}</div> : <div className="operations-empty"><strong>No critical or high alerts in this scope</strong><p>Lower-severity events remain available in the alert stream.</p></div>}</article>

      <aside className="panel operations-next-action"><span className="discovery-eyebrow">Recommended next</span><h3>{dashboard.workflow.nextAction}</h3><div>{dashboard.workflow.cards.map((card) => <article key={card.id}><span className={`workflow-pill workflow-pill-${card.status}`}>{card.status}</span><strong>{card.label}</strong><p>{card.detail}</p></article>)}</div></aside></div>

    <details className="panel operations-definitions"><summary>Data quality and metric definitions <span>{role.partial ? "Partial data" : `${role.period} · ${role.timezone}`}</span></summary><p>Counts distinguish loaded alerts, incident projections, approvals, workflow events, and closures. They are not interchangeable totals.</p></details>
  </section>;
}
