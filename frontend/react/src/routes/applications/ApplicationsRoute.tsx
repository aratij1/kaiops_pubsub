import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { useRouteRuntime } from "../../app/routeRuntime";
import { applicationDetailsQueryOptions, applicationsQueryOptions } from "../../services/applications";

export default function ApplicationsRoute() {
  const { session, dashboard } = useRouteRuntime();
  const location = useLocation();
  const navigate = useNavigate();
  const legacyKnowledgeWorkspace = new URLSearchParams(location.search).get("workspace") === "knowledge";
  const applications = useQuery(applicationsQueryOptions(session.accessToken));
  const [selectedId, setSelectedId] = useState("");
  const rows = useMemo(() => {
    const registered = applications.data || [];
    const names = new Set(registered.map((row) => String(row.name || "").toLowerCase()));
    const managedScopes = new Set(["kaims", "telemetry"]);
    const observed = dashboard.observedProjects.filter((name) => !names.has(name.toLowerCase())).map((name) => {
      const managedPlatform = managedScopes.has(name.toLowerCase());
      return { id: `observed:${name}`, name, status: managedPlatform ? "Managed platform" : "Observed", environment: managedPlatform ? "platform" : "-", owner_team: managedPlatform ? "KaiMS platform" : "Not registered", technology: managedPlatform ? "Built-in monitoring" : "Alert traffic", managed_platform: managedPlatform };
    });
    return [...registered, ...observed];
  }, [applications.data, dashboard.observedProjects]);
  useEffect(() => { if (!selectedId && rows.length) setSelectedId(String(rows[0].id)); }, [rows, selectedId]);
  const registeredId = selectedId.startsWith("observed:") ? "" : selectedId;
  const history = useQuery(applicationDetailsQueryOptions(session.accessToken, registeredId, "history"));
  const validations = useQuery(applicationDetailsQueryOptions(session.accessToken, registeredId, "validations"));
  const dashboards = useQuery(applicationDetailsQueryOptions(session.accessToken, registeredId, "dashboards"));
  const selected = applications.data?.find((row) => String(row.id) === registeredId);
  const details = [["Onboarding History", history.data], ["Validation Results", validations.data], ["Dashboards", dashboards.data]] as const;
  const refresh = () => { applications.refetch(); dashboard.refreshProjects(); };
  if (legacyKnowledgeWorkspace) return null;
  return <section className="grid single-col"><article className="panel"><div className="panel-head"><div><h2>Application inventory</h2><p>Registered applications plus services KaiMS has discovered from live alert traffic.</p></div><button className="button-secondary" type="button" onClick={refresh} disabled={applications.isFetching}>{applications.isFetching ? "Refreshing..." : "Refresh inventory"}</button></div>
    {applications.error ? <p className="error">{applications.error.message}</p> : null}<div className="table-wrap"><table><thead><tr><th>Name</th><th>Environment</th><th>Owner</th><th>Technology</th><th>Registration</th><th>Action</th></tr></thead><tbody>{rows.map((row) => { const observed=String(row.id).startsWith("observed:"); const managed=Boolean("managed_platform" in row && row.managed_platform); return <tr key={row.id} className={String(row.id) === selectedId ? "row-selected" : ""}><td><strong>{row.name}</strong></td><td>{row.environment || "-"}</td><td>{row.owner_team || "-"}</td><td>{row.technology || "-"}</td><td><span className={`pill ${observed && !managed ? "status-awaiting_approval" : "status-open"}`}>{managed ? "Managed—built in" : observed ? "Observed—not onboarded" : row.status || "Registered"}</span></td><td>{managed ? <span className="field-hint">No onboarding required</span> : <button className="button-secondary" type="button" onClick={() => observed ? navigate("/integrations") : setSelectedId(String(row.id))}>{observed ? "Onboard" : "Inspect"}</button>}</td></tr>; })}{!applications.isLoading && !rows.length ? <tr><td colSpan={6}>No applications have been registered or observed.</td></tr> : null}</tbody></table></div>
  </article>{selected ? <article className="panel"><div className="panel-head"><div><h2>{selected.name}</h2><p>{selected.metrics_endpoint || "No metrics endpoint supplied"}</p></div></div><div className="stat-grid"><div className="stat-card"><strong>Environment</strong><span>{selected.environment || "-"}</span></div><div className="stat-card"><strong>Region</strong><span>{selected.region || "-"}</span></div><div className="stat-card"><strong>Namespace</strong><span>{selected.namespace || "-"}</span></div><div className="stat-card"><strong>Status</strong><span>{selected.status || "-"}</span></div></div>{details.map(([title, detailRows]) => <section key={title}><h3>{title}</h3><div className="table-wrap"><table><thead><tr><th>Record</th></tr></thead><tbody>{detailRows?.map((row, index) => <tr key={index}><td><pre className="result">{JSON.stringify(row, null, 2)}</pre></td></tr>)}{!detailRows?.length ? <tr><td>No {title.toLowerCase()} available.</td></tr> : null}</tbody></table></div></section>)}</article> : null}</section>;
}
