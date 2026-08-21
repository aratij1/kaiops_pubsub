import { useState } from "react";
import { Gauge, RefreshCw, Route } from "lucide-react";

import { service360, type Service360 } from "./cloudOpsApi";
import "./CloudOpsRoute.css";

export default function Service360Route() {
  const [projectId, setProjectId] = useState("demo-project");
  const [serviceId, setServiceId] = useState("checkout-api");
  const [environment, setEnvironment] = useState("prod");
  const [view, setView] = useState<Service360 | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      setView(await service360(projectId, serviceId, environment || undefined));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load service 360");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cloud-ops-route" aria-labelledby="service-360-title">
      <article className="cloud-ops-panel">
        <header>
          <div>
            <h2 id="service-360-title">Service 360</h2>
            <p>Readiness, mapped resources, and service ownership context from the normalized cloud inventory.</p>
          </div>
          <button type="button" className="button-secondary" onClick={refresh} disabled={busy || !projectId || !serviceId}>
            <RefreshCw size={16} /> Load service
          </button>
        </header>
        <div className="cloud-ops-toolbar">
          <label><span>Project ID</span><input value={projectId} onChange={(event) => setProjectId(event.target.value)} /></label>
          <label><span>Service ID</span><input value={serviceId} onChange={(event) => setServiceId(event.target.value)} /></label>
          <label><span>Environment</span><input value={environment} onChange={(event) => setEnvironment(event.target.value)} /></label>
        </div>
      </article>

      {error ? <div className="cloud-ops-error" role="alert">{error}</div> : null}

      {view ? (
        <article className="cloud-ops-panel">
          <header>
            <div>
              <h2>{view.service_id}</h2>
              <p>{view.project_id} · {view.environment || "all environments"}</p>
            </div>
            <span className="cloud-ops-badge">{view.resources.length} resources</span>
          </header>
          <div className="cloud-ops-readiness">
            <div className="cloud-ops-readiness-score"><Gauge size={24} />{Number(view.readiness.score ?? 0)}</div>
            <div>
              <h3>Readiness signals</h3>
              <p>{Object.entries(view.health).map(([key, count]) => `${count} ${key}`).join(" · ") || "No health signals yet"}</p>
              <p>{view.relationships.length} topology relationships · {view.readiness_state}</p>
            </div>
          </div>
          <div className="cloud-ops-grid">
            {view.resources.map((resource) => (
              <article className="cloud-ops-card" key={resource.id}>
                <header>
                  <div>
                    <h3>{resource.display_name}</h3>
                    <p>{resource.resource_type} · {resource.region || "global"}</p>
                  </div>
                  <Route size={18} />
                </header>
                <div className="cloud-ops-meta"><span>{resource.provider}</span><span>{resource.status}</span></div>
              </article>
            ))}
          </div>
        </article>
      ) : <div className="cloud-ops-empty">Load a service to see its readiness context.</div>}
    </section>
  );
}
