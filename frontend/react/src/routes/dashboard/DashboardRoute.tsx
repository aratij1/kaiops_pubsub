import { useRouteRuntime } from "../../app/routeRuntime";

const CORE_PROJECTS = ["KaiOps", "Telemetry"];

export default function DashboardRoute() {
  const { dashboard } = useRouteRuntime();
  const role = dashboard.role;
  return <section className="grid single-col">
    <article className={`panel role-dashboard role-dashboard-${role.kind.toLowerCase()}`}>
      <div className="panel-head role-dashboard-header"><div><span className="discovery-eyebrow">{role.kind} dashboard</span><h2>{role.title}</h2><p>{role.description}</p></div><div className="role-dashboard-window"><span>{role.period}</span><strong>{role.timezone}</strong><span className={`workflow-pill ${role.partial ? "workflow-pill-idle" : role.refreshing ? "workflow-pill-active" : "workflow-pill-clear"}`}>{role.partial ? "partial data" : role.refreshing ? "refreshing" : "current data"}</span></div></div>
      <div className="role-dashboard-grid">{role.cards.map((card) => { const accessible = dashboard.allowedTabs.includes(card.tab); return <article className={`role-attention-card is-${card.tone}`} key={`${role.kind}-${card.label}`}><span>{card.label}</span><strong>{card.value}</strong><p>{card.detail}</p><button type="button" className="button-secondary" disabled={!accessible} title={accessible ? `Open ${card.label}` : "This destination is not available to your role"} onClick={() => accessible && dashboard.openSection(card.tab)}>View records</button></article>; })}</div>
      <details className="role-dashboard-definitions"><summary>Metric definitions and data quality</summary><ul>{role.cards.map((card) => <li key={`definition-${card.label}`}><strong>{card.label}:</strong> {card.detail}</li>)}</ul><p>Counts distinguish currently loaded alerts, incident projections, approval records, workflow events, and closures. They are not interchangeable totals.</p></details>
    </article>
    <div className="dashboard-secondary-grid">
      <article className="panel monitoring-projects-panel"><div className="panel-head"><div><span className="discovery-eyebrow">Scope</span><h2>Monitoring projects</h2><p>Choose the project used by alerts, incidents, and evidence.</p></div><button type="button" className="button-secondary" onClick={dashboard.refreshProjects}>Refresh</button></div><div className="monitoring-project-grid">{CORE_PROJECTS.map((name) => { const project = dashboard.projects.find((row) => String(row.name || "").trim().toLowerCase() === name.toLowerCase()); const selected = dashboard.selectedProject.toLowerCase() === name.toLowerCase(); return <button type="button" className={`monitoring-project-card ${selected ? "is-selected" : ""}`} key={name} onClick={() => dashboard.selectProject(name)}><span className="monitoring-project-icon">{name === "Telemetry" ? "OT" : "KO"}</span><span className="monitoring-project-copy"><strong>{name}</strong><small>{project?.namespace || name.toLowerCase()} namespace</small><code>{project?.metrics_endpoint || (name === "Telemetry" ? "Prometheus :19090" : "API Gateway metrics")}</code></span><span className={`pill ${String(project?.status || "").includes("failed") ? "status-failed" : "status-closed"}`}>{project?.status || "registered"}</span></button>; })}</div></article>
      <article className="panel workflow-guide-panel"><div className="panel-head"><div><span className="discovery-eyebrow">Next action</span><h2>Workflow health</h2></div></div><p className="scope-note">{dashboard.workflow.nextAction}</p><div className="workflow-guide-grid">{dashboard.workflow.cards.map((card) => <div className="workflow-guide-card" key={card.id}><strong>{card.label}</strong><span className={`workflow-pill workflow-pill-${card.status}`}>{card.status.toUpperCase()}</span><p>{card.detail}</p></div>)}</div></article>
    </div>
  </section>;
}
