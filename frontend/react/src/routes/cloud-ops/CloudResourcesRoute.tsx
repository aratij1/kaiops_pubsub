import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Boxes, ChevronRight, CircleAlert, GitBranch, Layers3, Network, RefreshCw, Search, Server, Workflow, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useRouteRuntimeSlice } from "../../app/routeRuntime";
import { useSession } from "../../app/SessionContext";
import { listResources, serviceTopology, type CloudResource } from "./cloudOpsApi";
import "./CloudOpsRoute.css";

export type ResourceDomain = "Applications" | "Services" | "Cloud" | "Kubernetes" | "Infrastructure" | "Databases" | "Messaging" | "Data Pipelines";
const DOMAINS: ResourceDomain[] = ["Applications", "Services", "Cloud", "Kubernetes", "Infrastructure", "Databases", "Messaging", "Data Pipelines"];

export function resourceDomain(resource: Pick<CloudResource, "resource_type" | "provider">): ResourceDomain {
  const value = `${resource.resource_type} ${resource.provider}`.toLowerCase();
  if (/database|mysql|postgres|oracle|sqlserver|db2|rds|cosmos/.test(value)) return "Databases";
  if (/kafka|queue|topic|rabbit|servicebus|pubsub|sqs|sns/.test(value)) return "Messaging";
  if (/airflow|pipeline|scheduler|dataflow|databricks/.test(value)) return "Data Pipelines";
  if (/kubernetes|cluster|namespace|pod|deployment|workload|container|aks|eks|gke/.test(value)) return "Kubernetes";
  if (/service|api|endpoint|function/.test(value)) return "Services";
  if (/application|app/.test(value)) return "Applications";
  if (/\bvm\b|virtual[_ -]?machine|host|server|network|load.?balancer|disk|compute/.test(value)) return "Infrastructure";
  return "Cloud";
}

export function resourcesInProject(rows: CloudResource[], projectId: string) {
  const scope = projectId.trim().toLowerCase();
  return scope ? rows.filter((row) => String(row.project_id || "").trim().toLowerCase() === scope) : [];
}

const searchable = (row: CloudResource) => [row.display_name, row.provider_resource_id, row.resource_type, row.provider, row.region, row.environment, row.service_id].filter(Boolean).join(" ").toLowerCase();
const readableTime = (value?: string) => { const parsed = new Date(value || ""); return value && !Number.isNaN(parsed.getTime()) ? parsed.toLocaleString() : "Not recorded"; };
const isSimulator = (row: CloudResource) => row.provider.toLowerCase() === "simulator" || row.provider_resource_id.toLowerCase().startsWith("simulator://");

export default function CloudResourcesRoute() {
  const navigate = useNavigate();
  const { accessToken } = useSession();
  const dashboard = useRouteRuntimeSlice("dashboard");
  // Use the same authoritative workspace list as the application shell. The
  // registry rows can lag behind built-in/onboarded scopes; falling back to
  // their first row silently switched a KaiMS session to another customer.
  const projects = useMemo(() => [...new Set(dashboard.observedProjects.map((item) => String(item || "").trim()).filter(Boolean))], [dashboard.observedProjects]);
  const activeProject = projects.find((item) => item.toLowerCase() === dashboard.selectedProject.trim().toLowerCase()) || dashboard.selectedProject.trim();
  const [projectId, setProjectId] = useState(activeProject);
  const [serviceId, setServiceId] = useState("");
  const [environment, setEnvironment] = useState("");
  const [resources, setResources] = useState<CloudResource[]>([]);
  const [domain, setDomain] = useState<ResourceDomain | "All">("All");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [selectedId, setSelectedId] = useState("");
  const [relationships, setRelationships] = useState<Array<Record<string, unknown>>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    const scope = projectId.trim();
    if (!accessToken || !scope) { setResources([]); setSelectedId(""); return; }
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError("");
    try {
      const rows = resourcesInProject(await listResources(accessToken, scope, serviceId.trim() || undefined, environment.trim() || undefined, controller.signal), scope);
      if (controller.signal.aborted) return;
      setResources(rows);
      setSelectedId((current) => rows.some((item) => item.id === current) ? current : (rows[0]?.id ?? ""));
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load resource inventory");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }, [accessToken, environment, projectId, serviceId]);

  useEffect(() => {
    if (activeProject !== projectId) { request.current?.abort(); setResources([]); setSelectedId(""); setProjectId(activeProject); }
  }, [activeProject, projectId]);
  useEffect(() => { void refresh(); return () => request.current?.abort(); }, [refresh]);

  const counts = useMemo(() => Object.fromEntries(DOMAINS.map((item) => [item, resources.filter((row) => resourceDomain(row) === item).length])), [resources]);
  const statuses = useMemo(() => [...new Set(resources.map((row) => row.status).filter(Boolean))].sort(), [resources]);
  const filtered = useMemo(() => resources.filter((row) => (domain === "All" || resourceDomain(row) === domain) && (status === "all" || row.status === status) && (!query.trim() || searchable(row).includes(query.trim().toLowerCase()))), [domain, query, resources, status]);
  const selected = resources.find((row) => row.id === selectedId) ?? null;
  const serviceCount = new Set(resources.map((row) => row.service_id).filter(Boolean)).size;

  useEffect(() => {
    let active = true;
    if (!selected?.service_id || !selected.project_id) { setRelationships([]); return undefined; }
    void serviceTopology(accessToken, selected.project_id, selected.service_id, selected.environment || undefined).then((result) => { if (active) setRelationships(result.edges); }).catch(() => { if (active) setRelationships([]); });
    return () => { active = false; };
  }, [accessToken, selected?.environment, selected?.id, selected?.project_id, selected?.service_id]);

  return <section className="cloud-ops-route resource-explorer" aria-labelledby="cloud-resources-title">
    <article className="cloud-ops-panel resource-explorer-header"><header><div><span className="resource-eyebrow">Operational digital twin</span><h2 id="cloud-resources-title">Application resources</h2><p>Verified resources discovered for the project selected at sign-in, with health, mapping, topology, and provenance.</p></div><button type="button" className="button-secondary" onClick={() => void refresh()} disabled={busy || !projectId}><RefreshCw className={busy ? "spin" : ""} size={16} /> {busy ? "Refreshing…" : "Refresh"}</button></header>
      <form className="resource-scope-bar" onSubmit={(event) => { event.preventDefault(); void refresh(); }}><label><span>Onboarded project</span><select value={projectId} onChange={(event) => { setProjectId(event.target.value); dashboard.selectProject(event.target.value); }} disabled={!projects.length}>{projects.length ? projects.map((name) => <option key={name} value={name}>{name}</option>) : <option value="">No onboarded projects</option>}</select></label><label><span>Mapped service</span><input placeholder="All services" value={serviceId} onChange={(event) => setServiceId(event.target.value)} /></label><label><span>Environment</span><input placeholder="All environments" value={environment} onChange={(event) => setEnvironment(event.target.value)} /></label><button type="submit" className="button-primary" disabled={busy || !projectId}>Apply scope</button></form>
      <div className="resource-scope-summary"><strong>{projectId || "No project selected"}</strong><span>{resources.length} verified resource{resources.length === 1 ? "" : "s"}</span><span>{serviceCount} mapped service{serviceCount === 1 ? "" : "s"}</span></div>
    </article>
    {error ? <div className="cloud-ops-error" role="alert">{error}</div> : null}
    {!projects.length ? <div className="cloud-ops-error" role="alert"><CircleAlert size={17} /> Resource discovery requires an onboarded project.</div> : null}
    <div className="resource-explorer-layout">
      <nav className="resource-domain-sidebar" aria-label="Resource domains"><button type="button" className={domain === "All" ? "active" : ""} onClick={() => setDomain("All")}><Layers3 size={17} /><span>All resources</span><strong>{resources.length}</strong></button>{DOMAINS.map((item) => <button type="button" key={item} className={domain === item ? "active" : ""} onClick={() => setDomain(item)}><Boxes size={17} /><span>{item}</span><strong>{counts[item] ?? 0}</strong></button>)}</nav>
      <main className="resource-results"><div className="resource-filter-bar"><label className="resource-search"><Search size={17} /><span className="sr-only">Search resources</span><input aria-label="Search resources" placeholder="Search name, identity, provider, region…" value={query} onChange={(event) => setQuery(event.target.value)} />{query ? <button type="button" aria-label="Clear search" onClick={() => setQuery("")}><X size={15} /></button> : null}</label><label><span className="sr-only">Health status</span><select aria-label="Health status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All health states</option>{statuses.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><span className="resource-result-count">{filtered.length} of {resources.length}</span></div>
        <div className="resource-list" aria-busy={busy}>{filtered.map((row) => <button type="button" className={`resource-list-row ${selectedId === row.id ? "selected" : ""}`} key={row.id} onClick={() => setSelectedId(row.id)}><span className="resource-kind-icon"><Server size={18} /></span><span className="resource-primary"><span className="resource-row-heading"><strong>{row.display_name}</strong><span className={`resource-health health-${row.status.toLowerCase()}`}><Activity size={13} />{row.status}</span></span><code className="resource-identity">{row.provider_resource_id}</code><span className="resource-row-meta"><span><small>Type</small><b>{row.resource_type}</b></span><span><small>Mapped service</small><b>{row.service_id || "Not mapped"}</b></span><span><small>Scope</small><b>{row.environment || "unscoped"} · {row.region || "global"}</b></span></span></span><ChevronRight size={17} /></button>)}{!filtered.length && !busy ? resources.length ? <div className="cloud-ops-empty">No resources match these filters.</div> : <div className="cloud-ops-empty"><strong>No discovered resources for {projectId || "this project"}</strong><span>Validate a provider connection and run discovery. Other projects are intentionally hidden.</span><button type="button" className="button-primary" onClick={() => navigate("/cloud-ops/connections")}>Configure discovery</button></div> : null}</div>
      </main>
      <aside className="resource-detail" aria-label="Resource details">{selected ? <><div className="resource-detail-heading"><span className="resource-kind-icon"><Server size={20} /></span><div><span className="resource-eyebrow">{resourceDomain(selected)}</span><h3>{selected.display_name}</h3></div></div><span className={`resource-health health-${selected.status.toLowerCase()}`}><Activity size={13} />{selected.status}</span>{isSimulator(selected) ? <p className="resource-simulation-note"><CircleAlert size={15} /> Simulated discovery record—not live cloud telemetry.</p> : null}<dl><div><dt>Project</dt><dd>{selected.project_id}</dd></div><div><dt>Stable identity</dt><dd><code>{selected.id}</code></dd></div><div><dt>Provider identity</dt><dd>{selected.provider_resource_id}</dd></div><div><dt>Discovery provider</dt><dd>{selected.provider}</dd></div><div><dt>Mapped service</dt><dd>{selected.service_id || "Not mapped"}</dd></div><div><dt>Environment</dt><dd>{selected.environment || "Not classified"}</dd></div><div><dt>Last discovered</dt><dd>{readableTime(selected.discovered_at)}</dd></div></dl><section className="resource-relationships"><h4><GitBranch size={16} /> Relationships</h4>{relationships.length ? relationships.slice(0, 8).map((edge, index) => <div key={String(edge.id ?? index)}><Network size={14} /><span>{String(edge.relationship_type ?? edge.type ?? "RELATED_TO")}</span><small>{String(edge.target_resource_id ?? edge.target_id ?? "resource")}</small></div>) : <p>{selected.service_id ? "No verified relationships returned for this scope." : "Map this resource to a service to load topology."}</p>}</section><section className="resource-provenance"><h4><Workflow size={16} /> Provenance</h4><p>Source: {isSimulator(selected) ? "simulated provider discovery" : "provider discovery"}</p><p>Connection: <code>{selected.connection_id}</code></p></section></> : <div className="cloud-ops-empty">Select a resource to inspect its operational context.</div>}</aside>
    </div>
  </section>;
}
