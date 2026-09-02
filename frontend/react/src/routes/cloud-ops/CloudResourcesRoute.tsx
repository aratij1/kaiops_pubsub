import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Boxes, ChevronRight, GitBranch, Layers3, Network, RefreshCw, Search, Server, Workflow, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

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

function searchable(resource: CloudResource) {
  return [resource.display_name, resource.provider_resource_id, resource.resource_type, resource.provider, resource.region, resource.environment, resource.service_id].filter(Boolean).join(" ").toLowerCase();
}

function readableTime(value?: string) {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export default function CloudResourcesRoute() {
  const navigate = useNavigate();
  const { accessToken } = useSession();
  const [projectId, setProjectId] = useState("demo-project");
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
  const refreshSequence = useRef(0);

  function scopeChanged(update: () => void) {
    refreshSequence.current += 1;
    setBusy(false);
    setError("");
    update();
  }

  async function refresh() {
    const sequence = ++refreshSequence.current;
    setBusy(true); setError("");
    try {
      const rows = await listResources(accessToken, projectId || undefined, serviceId || undefined, environment || undefined);
      if (sequence !== refreshSequence.current) return;
      setResources(rows);
      setSelectedId((current) => rows.some((item) => item.id === current) ? current : (rows[0]?.id ?? ""));
    } catch (err) {
      if (sequence === refreshSequence.current) setError(err instanceof Error ? err.message : "Unable to load resource inventory");
    } finally {
      if (sequence === refreshSequence.current) setBusy(false);
    }
  }

  useEffect(() => { if (accessToken) void refresh(); }, [accessToken]);
  const counts = useMemo(() => Object.fromEntries(DOMAINS.map((item) => [item, resources.filter((resource) => resourceDomain(resource) === item).length])), [resources]);
  const statuses = useMemo(() => [...new Set(resources.map((resource) => resource.status).filter(Boolean))].sort(), [resources]);
  const filtered = useMemo(() => resources.filter((resource) => (domain === "All" || resourceDomain(resource) === domain) && (status === "all" || resource.status === status) && (!query.trim() || searchable(resource).includes(query.trim().toLowerCase()))), [domain, query, resources, status]);
  const selected = resources.find((resource) => resource.id === selectedId) ?? null;

  useEffect(() => {
    let active = true;
    if (!selected?.service_id || !selected.project_id) { setRelationships([]); return undefined; }
    void serviceTopology(accessToken, selected.project_id, selected.service_id, selected.environment || undefined).then((result) => { if (active) setRelationships(result.edges); }).catch(() => { if (active) setRelationships([]); });
    return () => { active = false; };
  }, [accessToken, selected?.id]);

  return <section className="cloud-ops-route resource-explorer" aria-labelledby="cloud-resources-title">
    <article className="cloud-ops-panel resource-explorer-header"><header><div><span className="resource-eyebrow">Operational Digital Twin</span><h2 id="cloud-resources-title">Resource Explorer</h2><p>Search the operational estate, inspect health and provenance, and follow deterministic topology relationships.</p></div><button type="button" className="button-secondary" onClick={refresh} disabled={busy}><RefreshCw className={busy ? "spin" : ""} size={16} /> {busy ? "Refreshing…" : "Refresh"}</button></header>
      <form className="cloud-ops-toolbar" onSubmit={(event) => { event.preventDefault(); void refresh(); }}><label><span>Project ID</span><input value={projectId} onChange={(event) => scopeChanged(() => setProjectId(event.target.value))} /></label><label><span>Service ID</span><input placeholder="All services" value={serviceId} onChange={(event) => scopeChanged(() => setServiceId(event.target.value))} /></label><label><span>Environment</span><input placeholder="All environments" value={environment} onChange={(event) => scopeChanged(() => setEnvironment(event.target.value))} /></label><button type="submit" className="button-primary" disabled={busy}>Apply scope</button></form>
    </article>
    {error ? <div className="cloud-ops-error" role="alert">{error}</div> : null}
    <div className="resource-explorer-layout">
      <nav className="resource-domain-sidebar" aria-label="Resource domains"><button className={domain === "All" ? "active" : ""} onClick={() => setDomain("All")}><Layers3 size={17} /><span>All resources</span><strong>{resources.length}</strong></button>{DOMAINS.map((item) => <button key={item} className={domain === item ? "active" : ""} onClick={() => setDomain(item)}><Boxes size={17} /><span>{item}</span><strong>{counts[item] ?? 0}</strong></button>)}</nav>
      <main className="resource-results"><div className="resource-filter-bar"><label className="resource-search"><Search size={17} /><span className="sr-only">Search resources</span><input aria-label="Search resources" placeholder="Search name, identity, provider, region…" value={query} onChange={(event) => setQuery(event.target.value)} />{query ? <button type="button" aria-label="Clear search" onClick={() => setQuery("")}><X size={15} /></button> : null}</label><label><span className="sr-only">Health status</span><select aria-label="Health status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All health states</option>{statuses.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><span className="resource-result-count" aria-live="polite">{filtered.length} of {resources.length}</span></div>
        <div className="resource-list" aria-busy={busy}>{filtered.map((resource) => <button type="button" className={`resource-list-row ${selectedId === resource.id ? "selected" : ""}`} key={resource.id} onClick={() => setSelectedId(resource.id)}><span className="resource-kind-icon"><Server size={18} /></span><span className="resource-primary"><strong>{resource.display_name}</strong><small>{resource.provider_resource_id}</small></span><span><small>Type</small>{resource.resource_type}</span><span><small>Scope</small>{resource.environment || "unscoped"} · {resource.region || "global"}</span><span className={`resource-health health-${resource.status.toLowerCase()}`}><Activity size={13} />{resource.status}</span><ChevronRight size={17} /></button>)}{!filtered.length && !busy ? resources.length ? <div className="cloud-ops-empty">No resources match the active filters. Clear the search or adjust the scope.</div> : <div className="cloud-ops-empty"><strong>No discovered resources in this project</strong><span>Validate a provider connection and run discovery to populate the operational estate.</span><button type="button" className="button-primary" onClick={() => navigate("/cloud-ops/connections")}>Configure discovery</button></div> : null}</div>
      </main>
      <aside className="resource-detail" aria-label="Resource details">{selected ? <><div className="resource-detail-heading"><span className="resource-kind-icon"><Server size={20} /></span><div><span className="resource-eyebrow">{resourceDomain(selected)}</span><h3>{selected.display_name}</h3></div></div><span className={`resource-health health-${selected.status.toLowerCase()}`}><Activity size={13} />{selected.status}</span><dl><div><dt>Stable identity</dt><dd><code>{selected.id}</code></dd></div><div><dt>Provider identity</dt><dd>{selected.provider_resource_id}</dd></div><div><dt>Provider</dt><dd>{selected.provider}</dd></div><div><dt>Service owner</dt><dd>{selected.service_id || "Not mapped"}</dd></div><div><dt>Environment</dt><dd>{selected.environment || "Not classified"}</dd></div><div><dt>Last discovered</dt><dd>{readableTime(selected.discovered_at)}</dd></div></dl><section className="resource-relationships"><h4><GitBranch size={16} /> Relationships</h4>{relationships.length ? relationships.slice(0, 8).map((edge, index) => <div key={String(edge.id ?? index)}><Network size={14} /><span>{String(edge.relationship_type ?? edge.type ?? "RELATED_TO")}</span><small>{String(edge.target_resource_id ?? edge.target_id ?? "resource")}</small></div>) : <p>{selected.service_id ? "No verified relationships returned for this resource scope." : "Map this resource to a service to load topology."}</p>}</section><section className="resource-provenance"><h4><Workflow size={16} /> Provenance</h4><p>Source: deterministic provider discovery</p><p>Connection: <code>{selected.connection_id}</code></p></section></> : <div className="cloud-ops-empty">Select a resource to inspect its operational context.</div>}</aside>
    </div>
  </section>;
}
