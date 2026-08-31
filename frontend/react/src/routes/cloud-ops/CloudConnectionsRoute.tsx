import { useCallback, useEffect, useRef, useState } from "react";
import { Cloud, Play, RefreshCw, ShieldCheck } from "lucide-react";

import { useRouteRuntimeSlice } from "../../app/routeRuntime";
import {
  createSimulatorConnection,
  discoverConnection,
  listConnections,
  validateConnection,
  type CloudConnection,
} from "./cloudOpsApi";
import "./CloudOpsRoute.css";

export default function CloudConnectionsRoute() {
  const { accessToken } = useRouteRuntimeSlice("session");
  const [projectId, setProjectId] = useState("demo-project");
  const [serviceId, setServiceId] = useState("checkout-api");
  const [environment, setEnvironment] = useState("prod");
  const [name, setName] = useState("Simulator landing zone");
  const [connections, setConnections] = useState<CloudConnection[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const selectedProjectRef = useRef(projectId.trim());
  const refreshControllerRef = useRef<AbortController | null>(null);
  const actionControllerRef = useRef<AbortController | null>(null);
  const normalizedProjectId = projectId.trim();
  selectedProjectRef.current = normalizedProjectId;

  const refresh = useCallback(async () => {
    const scopeProjectId = normalizedProjectId;
    if (!accessToken || !scopeProjectId) return;
    refreshControllerRef.current?.abort();
    const controller = new AbortController();
    refreshControllerRef.current = controller;
    setBusy("refresh");
    setError("");
    try {
      const rows = await listConnections(accessToken, scopeProjectId, controller.signal);
      if (!controller.signal.aborted && selectedProjectRef.current === scopeProjectId) setConnections(rows);
    } catch (err) {
      if (!controller.signal.aborted && selectedProjectRef.current === scopeProjectId) {
        setError(err instanceof Error ? err.message : "Unable to load cloud connections");
      }
    } finally {
      if (refreshControllerRef.current === controller) setBusy("");
    }
  }, [accessToken, normalizedProjectId]);

  useEffect(() => {
    refreshControllerRef.current?.abort();
    actionControllerRef.current?.abort();
    setConnections([]);
    setError("");
    if (!accessToken || !normalizedProjectId) return undefined;
    const timer = window.setTimeout(() => {
      void refresh();
    }, 250);
    return () => {
      window.clearTimeout(timer);
      refreshControllerRef.current?.abort();
      actionControllerRef.current?.abort();
    };
  }, [accessToken, normalizedProjectId, refresh]);

  async function createConnection() {
    const scopeProjectId = normalizedProjectId;
    if (!scopeProjectId) return;
    setBusy("create");
    setError("");
    try {
      const row = await createSimulatorConnection(accessToken, scopeProjectId, name.trim());
      if (selectedProjectRef.current === scopeProjectId && row.project_id === scopeProjectId) {
        setConnections((current) => [row, ...current.filter((item) => item.id !== row.id)]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create simulator connection");
    } finally {
      setBusy("");
    }
  }

  async function runConnectionAction(id: string, action: "validate" | "discover") {
    const scopeProjectId = normalizedProjectId;
    const connection = connections.find((item) => item.id === id);
    if (!connection || connection.project_id !== scopeProjectId) {
      setError("Connection actions are disabled because the selected project scope changed.");
      return;
    }
    actionControllerRef.current?.abort();
    const controller = new AbortController();
    actionControllerRef.current = controller;
    setBusy(`${action}:${id}`);
    setError("");
    try {
      if (action === "validate") await validateConnection(accessToken, id, controller.signal);
      else await discoverConnection(accessToken, id, scopeProjectId, serviceId.trim(), environment.trim(), controller.signal);
      if (!controller.signal.aborted && selectedProjectRef.current === scopeProjectId) await refresh();
    } catch (err) {
      if (!controller.signal.aborted && selectedProjectRef.current === scopeProjectId) {
        setError(err instanceof Error ? err.message : `Unable to ${action} connection`);
      }
    } finally {
      if (actionControllerRef.current === controller) setBusy("");
    }
  }

  return (
    <section className="cloud-ops-route" aria-labelledby="cloud-connections-title">
      <article className="cloud-ops-panel">
        <header>
          <div>
            <h2 id="cloud-connections-title">Provider connections</h2>
            <p>Start with the simulator provider, then plug in real cloud adapters behind the same contract.</p>
          </div>
          <button type="button" className="button-secondary" onClick={() => void refresh()} disabled={Boolean(busy)}>
            <RefreshCw size={16} /> Refresh
          </button>
        </header>

        <div className="cloud-ops-toolbar">
          <label>
            <span>Project ID</span>
            <input value={projectId} onChange={(event) => { setConnections([]); setProjectId(event.target.value); }} />
          </label>
          <label>
            <span>Connection name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label>
            <span>Service ID</span>
            <input value={serviceId} onChange={(event) => setServiceId(event.target.value)} />
          </label>
          <label>
            <span>Environment</span>
            <input value={environment} onChange={(event) => setEnvironment(event.target.value)} />
          </label>
          <button type="button" className="button-primary" onClick={createConnection} disabled={Boolean(busy || !normalizedProjectId || !name.trim())}>
            <Cloud size={16} /> Add simulator connection
          </button>
        </div>
      </article>

      {error ? <div className="cloud-ops-error" role="alert">{error}</div> : null}

      <div className="cloud-ops-grid">
        {connections.map((connection) => (
          <article className="cloud-ops-card" key={connection.id}>
            <header>
              <div>
                <h3>{connection.connection_name}</h3>
                <p>{connection.project_id} · {connection.provider_type}</p>
              </div>
              <span className="cloud-ops-badge">{connection.status}</span>
            </header>
            <div className="cloud-ops-meta">
              <span>Read: {connection.read_capability ? "enabled" : "disabled"}</span>
              <span>Write: {connection.write_capability ? "enabled" : "disabled"}</span>
              <span>Owner: {connection.connection_owner}</span>
            </div>
            <div className="cloud-ops-toolbar">
              <button type="button" className="button-secondary" onClick={() => runConnectionAction(connection.id, "validate")} disabled={Boolean(busy) || connection.project_id !== normalizedProjectId}>
                <ShieldCheck size={16} /> Validate
              </button>
              <button type="button" className="button-secondary" onClick={() => runConnectionAction(connection.id, "discover")} disabled={Boolean(busy) || connection.project_id !== normalizedProjectId}>
                <Play size={16} /> Discover
              </button>
            </div>
          </article>
        ))}
      </div>
      {!connections.length && !busy ? <div className="cloud-ops-empty">No cloud connections found for this project yet.</div> : null}
    </section>
  );
}
