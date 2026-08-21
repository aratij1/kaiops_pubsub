import { useEffect, useState } from "react";
import { Activity, Cloud, Gauge, RefreshCw } from "lucide-react";

import { operationsCockpit, type CockpitSummary } from "./cloudOpsApi";
import "./CloudOpsRoute.css";

export default function OperationsCockpitRoute() {
  const [projectId, setProjectId] = useState("demo-project");
  const [environment, setEnvironment] = useState("");
  const [summary, setSummary] = useState<CockpitSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      setSummary(await operationsCockpit(projectId || undefined, environment || undefined));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load operations cockpit");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <section className="cloud-ops-route" aria-labelledby="cloud-cockpit-title">
      <article className="cloud-ops-panel">
        <header>
          <div>
            <h2 id="cloud-cockpit-title">Operations cockpit</h2>
            <p>Cross-cloud service health, resource distribution, and readiness posture.</p>
          </div>
          <button type="button" className="button-secondary" onClick={refresh} disabled={busy}>
            <RefreshCw size={16} /> Refresh
          </button>
        </header>
        <div className="cloud-ops-toolbar">
          <label><span>Project ID</span><input value={projectId} onChange={(event) => setProjectId(event.target.value)} /></label>
          <label><span>Environment</span><input placeholder="optional" value={environment} onChange={(event) => setEnvironment(event.target.value)} /></label>
        </div>
      </article>

      {error ? <div className="cloud-ops-error" role="alert">{error}</div> : null}

      {summary ? (
        <>
          <div className="cloud-ops-grid">
            <article className="cloud-ops-card"><header><h3>Resources</h3><Cloud size={18} /></header><div className="cloud-ops-kpi">{summary.resource_count}</div><p>Discovered assets in scope</p></article>
            <article className="cloud-ops-card"><header><h3>Services</h3><Activity size={18} /></header><div className="cloud-ops-kpi">{summary.service_count}</div><p>Services with mapped inventory</p></article>
            <article className="cloud-ops-card"><header><h3>Health states</h3><Gauge size={18} /></header><div className="cloud-ops-meta">{Object.entries(summary.health).map(([key, value]) => <span key={key}>{value} {key}</span>)}</div></article>
          </div>
          <article className="cloud-ops-panel">
            <header><h2>Readiness board</h2><span className="cloud-ops-badge">{summary.readiness.length} services</span></header>
            <div className="cloud-ops-grid">
              {summary.readiness.map((row) => (
                <article className="cloud-ops-card" key={`${row.project_id}-${row.service_id}-${row.environment}`}>
                  <header><div><h3>{row.service_id}</h3><p>{row.project_id} · {row.environment}</p></div><span className="cloud-ops-badge">{row.readiness_state}</span></header>
                  <div className="cloud-ops-readiness"><div className="cloud-ops-readiness-score">{Math.round(row.overall_score * 100)}</div><p>{Object.entries(row.scores).map(([key, value]) => `${key}: ${Math.round(value * 100)}`).join(" · ")}</p></div>
                </article>
              ))}
            </div>
            {!summary.readiness.length ? <div className="cloud-ops-empty">No readiness scores yet. Save a service onboarding profile first.</div> : null}
          </article>
        </>
      ) : <div className="cloud-ops-empty">Load cockpit data to see cross-cloud posture.</div>}
    </section>
  );
}
