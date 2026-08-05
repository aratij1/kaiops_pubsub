import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { useRouteRuntime } from "../../app/routeRuntime";
import { applicationDetailsQueryOptions, applicationsQueryOptions } from "../../services/applications";

export default function ApplicationsRoute() {
  const { session } = useRouteRuntime();
  const location = useLocation();
  const legacyKnowledgeWorkspace = new URLSearchParams(location.search).get("workspace") === "knowledge";
  const applications = useQuery(applicationsQueryOptions(session.accessToken));
  const [selectedId, setSelectedId] = useState("");
  useEffect(() => { if (!selectedId && applications.data?.length) setSelectedId(String(applications.data[0].id)); }, [applications.data, selectedId]);
  const history = useQuery(applicationDetailsQueryOptions(session.accessToken, selectedId, "history"));
  const validations = useQuery(applicationDetailsQueryOptions(session.accessToken, selectedId, "validations"));
  const dashboards = useQuery(applicationDetailsQueryOptions(session.accessToken, selectedId, "dashboards"));
  const selected = applications.data?.find((row) => String(row.id) === selectedId);
  const details = [["Onboarding History", history.data], ["Validation Results", validations.data], ["Dashboards", dashboards.data]] as const;
  if (legacyKnowledgeWorkspace) return null;
  return <section className="grid single-col"><article className="panel"><div className="panel-head"><h2>Applications</h2><p>Registered applications and their real onboarding, validation, and dashboard artifacts.</p><button className="button-secondary" type="button" onClick={() => applications.refetch()} disabled={applications.isFetching}>{applications.isFetching ? "Refreshing..." : "Refresh"}</button></div>
    {applications.error ? <p className="error">{applications.error.message}</p> : null}<div className="table-wrap"><table><thead><tr><th>Name</th><th>Environment</th><th>Owner</th><th>Technology</th><th>Status</th><th>Action</th></tr></thead><tbody>{applications.data?.map((row) => <tr key={row.id} className={String(row.id) === selectedId ? "row-selected" : ""}><td>{row.name}</td><td>{row.environment || "-"}</td><td>{row.owner_team || "-"}</td><td>{row.technology || "-"}</td><td>{row.status || "-"}</td><td><button className="button-secondary" type="button" onClick={() => setSelectedId(String(row.id))}>Inspect</button></td></tr>)}{!applications.isLoading && !applications.data?.length ? <tr><td colSpan={6}>No applications registered.</td></tr> : null}</tbody></table></div>
  </article>{selected ? <article className="panel"><div className="panel-head"><h2>{selected.name}</h2><p>{selected.metrics_endpoint || "No metrics endpoint supplied"}</p></div><div className="stat-grid"><div className="stat-card"><strong>Environment</strong><span>{selected.environment || "-"}</span></div><div className="stat-card"><strong>Region</strong><span>{selected.region || "-"}</span></div><div className="stat-card"><strong>Namespace</strong><span>{selected.namespace || "-"}</span></div><div className="stat-card"><strong>Status</strong><span>{selected.status || "-"}</span></div></div>{details.map(([title, rows]) => <section key={title}><h3>{title}</h3><div className="table-wrap"><table><thead><tr><th>Record</th></tr></thead><tbody>{rows?.map((row, index) => <tr key={index}><td><pre className="result">{JSON.stringify(row, null, 2)}</pre></td></tr>)}{!rows?.length ? <tr><td>No {title.toLowerCase()} available.</td></tr> : null}</tbody></table></div></section>)}</article> : null}</section>;
}
