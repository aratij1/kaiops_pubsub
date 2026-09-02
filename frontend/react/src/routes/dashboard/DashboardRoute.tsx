import { Activity, ArrowRight, Bot, Check, CheckCircle2, CircleAlert, Clock3, FileCheck2, RefreshCw, RotateCcw, ShieldCheck, Siren, Sparkles } from "lucide-react";

import { useRouteRuntime, type IncidentRow } from "../../app/routeRuntime";
import { durableIncidentId } from "../../domain/incidentNavigation";
import "./DashboardRoute.css";

const terminal = (row: IncidentRow) => ["closed", "resolved", "recovered", "cancelled"].some((value) => String(row.status || "").toLowerCase().includes(value));
const incidentId = (row: IncidentRow) => durableIncidentId(row);
const title = (row: IncidentRow) => String(row.title || row.summary || `${row.service || "Service"} incident`);
const status = (row: IncidentRow) => String(row.status || "investigating").replaceAll("_", " ");
const isCritical = (row: IncidentRow) => ["critical", "sev1", "p1"].includes(String(row.severity || "").toLowerCase());
const isFailed = (row: IncidentRow) => ["failed", "validation_failed", "rollback_failed", "manual_intervention_required"].some((value) => String(row.status || "").toLowerCase().includes(value));
const pendingApprovalStates = new Set(["awaiting_approval", "pending_approval", "pending", "queued", "draft", "standby", "required"]);
const normalizeState = (value: unknown) => String(value || "").trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
export const needsDashboardApproval = (row: IncidentRow) => pendingApprovalStates.has(normalizeState(row.approval_status)) || ["awaiting_approval", "pending_approval", "approval_required"].includes(normalizeState(row.status));

function timeAgo(value: unknown) {
  const date = new Date(String(value || ""));
  if (!Number.isFinite(date.getTime())) return "Time unavailable";
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}

function WorkItem({ row, onOpen, action }: { row: IncidentRow; onOpen: () => void; action: string }) {
  const available = Boolean(incidentId(row));
  return <button type="button" className="oh-work-item" onClick={onOpen} disabled={!available} title={available ? undefined : "Incident identifier unavailable"}>
    <span className={`oh-severity is-${String(row.severity || "unknown").toLowerCase()}`}>{row.severity || "Unrated"}</span>
    <span><strong>{title(row)}</strong><small>{incidentId(row)} · {row.service || "Service unavailable"} · {timeAgo(row.updated_at || row.created_at)}</small></span>
    <span className="oh-work-action">{available ? action : "Cannot open"}<ArrowRight aria-hidden="true" /></span>
  </button>;
}

export default function DashboardRoute() {
  const { dashboard, incidents, approvals, executive } = useRouteRuntime();
  const active = incidents.rows.filter((row) => !terminal(row));
  const critical = active.filter(isCritical);
  const failed = active.filter(isFailed);
  const pending = approvals.rows.filter(needsDashboardApproval);
  const pendingIds = new Set(pending.map((row) => incidentId(row)));
  const attentionIds = new Set([...pending, ...failed, ...critical].map((row) => incidentId(row)).filter(Boolean));
  const kaiHandling = active.filter((row) => !attentionIds.has(incidentId(row)));
  const activeCount = active.length;
  const attentionCount = attentionIds.size;
  const kaiHandlingCount = kaiHandling.length;
  const recentlyResolved = [...executive.recentlyClosed].sort((left, right) => new Date(String(right.closed_at || right.updated_at || 0)).getTime() - new Date(String(left.closed_at || left.updated_at || 0)).getTime()).slice(0, 4);
  const autoResolved = recentlyResolved.filter((row) => String(row.execution_mode || "").toLowerCase().includes("auto")).length;
  const rollbackCount = incidents.rows.filter((row) => String(row.status || "").toLowerCase().includes("rollback")).length;
  const customerImpact = active.filter((row) => {
    const payload = row.projection_payload || {};
    return Boolean(payload.customer_impact || payload.business_impact || payload.impact);
  }).length;
  const closureDurations = executive.recentlyClosed.map((row) => {
    const start = new Date(String(row.created_at || "")).getTime();
    const end = new Date(String(row.closed_at || row.updated_at || "")).getTime();
    return Number.isFinite(start) && Number.isFinite(end) && end >= start ? end - start : null;
  }).filter((value): value is number => value !== null);
  const mttrMinutes = closureDurations.length ? Math.round(closureDurations.reduce((sum, value) => sum + value, 0) / closureDurations.length / 60_000) : null;
  const snapshotAt = incidents.page.snapshot_at || incidents.page.generated_at;
  const snapshotLabel = snapshotAt && Number.isFinite(new Date(snapshotAt).getTime())
    ? `Updated ${new Date(snapshotAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
    : "Update time unavailable";
  const pulse = [
    { label: "Active in view", value: activeCount, icon: Activity, open: () => dashboard.openSection("summary") },
    { label: "Critical in view", value: critical.length, icon: Siren, open: () => dashboard.openSection("summary") },
    { label: "Impact in view", value: customerImpact, icon: CircleAlert, open: () => dashboard.openSection("summary") },
    { label: "Pending decisions", value: pending.length, icon: FileCheck2, open: () => dashboard.openSection("approval") },
    { label: "Auto-resolved", value: autoResolved, icon: Sparkles, open: () => dashboard.openSection("closed") },
    { label: "MTTR", value: mttrMinutes === null ? "—" : `${mttrMinutes}m`, icon: Clock3, open: () => dashboard.openSection("executive") },
    { label: "Rollback rate", value: incidents.rows.length ? `${Math.round(rollbackCount / incidents.rows.length * 100)}%` : "—", icon: RotateCcw, open: () => dashboard.openSection("executive") },
  ];

  return <section className="operations-home">
    <header className={`oh-status ${attentionCount ? "needs-attention" : "is-clear"}`}>
      <div className="oh-status-icon">{attentionCount ? <CircleAlert aria-hidden="true" /> : <ShieldCheck aria-hidden="true" />}</div>
      <div><span>Production status · loaded project records</span><h2>{attentionCount ? `${attentionCount} item${attentionCount === 1 ? "" : "s"} need attention` : "No active attention items"}</h2><p>{attentionCount ? "Kai has ranked the loaded decisions and exceptions that may need human judgment." : `Kai is monitoring the loaded ${dashboard.selectedProject || "project"} scope.`}</p></div>
      <div className="oh-scope"><label>Project<select value={dashboard.selectedProject} onChange={(event) => dashboard.selectProject(event.target.value)}>{dashboard.observedProjects.map((project) => <option value={project} key={project}>{project}</option>)}</select></label><small aria-live="polite">{incidents.loading ? "Updating live data..." : snapshotLabel}</small><button type="button" disabled={incidents.loading} onClick={() => dashboard.refreshProjects()}><RefreshCw aria-hidden="true" /> {incidents.loading ? "Updating..." : "Refresh"}</button></div>
    </header>

    <section className="oh-pulse" aria-label="Operations pulse"><header><span>Operations pulse</span><small>Every metric opens its operational source</small></header><div>{pulse.map((metric) => { const Icon = metric.icon; return <button type="button" key={metric.label} onClick={metric.open}><Icon aria-hidden="true" /><span>{metric.label}</span><strong>{metric.value}</strong></button>; })}</div></section>

    <div className="oh-attention-grid">
      <section className="oh-lane needs-you"><header><div><FileCheck2 aria-hidden="true" /><span><small>Needs you</small><strong>Judgment, risk, and exceptions</strong></span></div><em>{attentionCount}</em></header><div>{pending.slice(0, 4).map((row) => <WorkItem key={`approval-${incidentId(row)}`} row={row} action="Review decision" onOpen={() => incidents.open(row)} />)}{failed.filter((row) => !pendingIds.has(incidentId(row))).slice(0, 3).map((row) => <WorkItem key={`failed-${incidentId(row)}`} row={row} action="Inspect failure" onOpen={() => incidents.open(row)} />)}{!attentionCount ? <div className="oh-empty"><CheckCircle2 aria-hidden="true" /><span><strong>Nothing needs your decision</strong><small>Kai has no pending approvals or failed actions in the loaded scope.</small></span></div> : null}</div>{attentionCount ? <button type="button" className="oh-lane-link" onClick={() => dashboard.openSection("approval")}>Open approval inbox <ArrowRight aria-hidden="true" /></button> : null}</section>
      <section className="oh-lane kai-handling"><header><div><Bot aria-hidden="true" /><span><small>Kai is handling</small><strong>Investigations and governed action</strong></span></div><em>{kaiHandlingCount}</em></header><div>{kaiHandling.slice(0, 6).map((row) => <WorkItem key={`kai-${incidentId(row)}`} row={row} action={status(row)} onOpen={() => incidents.open(row)} />)}{!kaiHandlingCount ? <div className="oh-empty"><Bot aria-hidden="true" /><span><strong>No in-progress Kai work</strong><small>New investigations will appear from backend incident state.</small></span></div> : null}</div>{activeCount ? <button type="button" className="oh-lane-link" onClick={() => dashboard.openSection("summary")}>Open incident inbox <ArrowRight aria-hidden="true" /></button> : null}</section>
    </div>

    <section className="oh-resolved"><header><div><CheckCircle2 aria-hidden="true" /><span><small>Recently resolved</small><h3>Verified outcomes from incident history</h3></span></div><button type="button" onClick={() => dashboard.openSection("closed")}>View history <ArrowRight aria-hidden="true" /></button></header>{recentlyResolved.length ? <div>{recentlyResolved.map((row) => <button type="button" key={`resolved-${incidentId(row)}`} onClick={() => incidents.open(row)}><span className="oh-resolved-check"><Check aria-hidden="true" /></span><span><strong>{title(row)}</strong><small>{incidentId(row)} · {row.service || "Service unavailable"}</small></span><span><strong>{String(row.execution_mode || "Resolution recorded").replaceAll("_", " ")}</strong><small>{timeAgo(row.closed_at || row.updated_at)}</small></span><ArrowRight aria-hidden="true" /></button>)}</div> : <div className="oh-empty"><CheckCircle2 aria-hidden="true" /><span><strong>No recent closures returned</strong><small>Resolved incidents will appear when the backend provides closure records.</small></span></div>}</section>

    <footer className="oh-truth"><ShieldCheck aria-hidden="true" /><span><strong>Observed data only.</strong> Counts and states come from the current API responses; unavailable KPIs are shown as unavailable.</span></footer>
  </section>;
}
