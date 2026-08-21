import { useEffect, useMemo, useState } from "react";
import { Database, RefreshCw, Server } from "lucide-react";

import { listResources, type CloudResource } from "./cloudOpsApi";
import "./CloudOpsRoute.css";

export default function CloudResourcesRoute() {
  const [projectId, setProjectId] = useState("demo-project");
  const [serviceId, setServiceId] = useState("");
  const [environment, setEnvironment] = useState("");
  const [resources, setResources] = useState<CloudResource[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const resourceTypes = useMemo(
    () => [...new Set(resources.map((resource) => resource.resource_type))].sort(),
    [resources],
  );

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      setResources(await listResources(projectId, serviceId || undefined, environment || undefined));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load resource inventory");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <section className="cloud-ops-route" aria-labelledby="cloud-resources-title">
      <article className="cloud-ops-panel">
        <header>
          <div>
            <h2 id="cloud-resources-title">Discovered inventory</h2>
            <p>Provider-normalized assets with tenant/project filters and service ownership hints.</p>
          </div>
          <button type="button" className="button-secondary" onClick={refresh} disabled={busy}>
            <RefreshCw size={16} /> Refresh
          </button>
        </header>
        <div className="cloud-ops-toolbar">
          <label><span>Project ID</span><input value={projectId} onChange={(event) => setProjectId(event.target.value)} /></label>
          <label><span>Service ID</span><input placeholder="optional" value={serviceId} onChange={(event) => setServiceId(event.target.value)} /></label>
          <label><span>Environment</span><input placeholder="optional" value={environment} onChange={(event) => setEnvironment(event.target.value)} /></label>
        </div>
        <div className="cloud-ops-meta">
          <span>{resources.length} resources</span>
          <span>{resourceTypes.length ? resourceTypes.join(", ") : "No resource types yet"}</span>
        </div>
      </article>

      {error ? <div className="cloud-ops-error" role="alert">{error}</div> : null}

      <div className="cloud-ops-grid">
        {resources.map((resource) => (
          <article className="cloud-ops-card" key={resource.id}>
            <header>
              <div>
                <h3>{resource.display_name}</h3>
                <p>{resource.provider_resource_id}</p>
              </div>
              <span className="cloud-ops-badge">{resource.status}</span>
            </header>
            <div className="cloud-ops-meta">
              <span><Server size={14} /> {resource.resource_type}</span>
              <span><Database size={14} /> {resource.provider}</span>
              <span>{resource.region || "global"}</span>
              <span>{resource.service_id || "unmapped"}</span>
            </div>
          </article>
        ))}
      </div>
      {!resources.length && !busy ? <div className="cloud-ops-empty">No resources discovered yet. Run discovery from Cloud Connections.</div> : null}
    </section>
  );
}
