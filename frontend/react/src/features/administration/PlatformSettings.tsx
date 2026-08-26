import { useCallback, useEffect, useState } from "react";
import { Activity, Bell, CheckCircle2, Database, KeyRound, RefreshCw, Server, Settings, ShieldAlert, ShieldCheck } from "lucide-react";

import { useRouteRuntime } from "../../app/routeRuntime";
import { ServiceHealth, StatusBadge } from "../../components/design-system";
import { fetchJson, formatUtcTimestamp } from "../../appHelpers.jsx";
import "./PlatformSettings.css";
import "./PlatformServiceControl.css";

interface PlatformServiceRow { service: string; capability: string; status: "healthy" | "degraded" | "unavailable"; status_code?: number | null; latency_ms?: number; detail?: string; }
interface PlatformHealth { status: string; observed_at: string; summary: { healthy: number; degraded: number; unavailable: number; total: number }; services: PlatformServiceRow[]; }

export default function PlatformSettings() {
  const { dashboard, safety, admin, session } = useRouteRuntime();
  const gatewayHealthy = !safety.summaryError;
  const landingHealthy = !safety.landingError;
  const [platformHealth, setPlatformHealth] = useState<PlatformHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState("");
  const refreshPlatformHealth = useCallback(async () => {
    setHealthLoading(true); setHealthError("");
    try {
      const data = await fetchJson("/api-gateway/operations/service-health", { headers: session.accessToken ? { Authorization: `Bearer ${session.accessToken}` } : {}, timeoutMs: 10000 }) as PlatformHealth;
      setPlatformHealth(data);
    } catch (error) { setHealthError(String((error as Error)?.message || error)); }
    finally { setHealthLoading(false); }
  }, [session.accessToken]);
  useEffect(() => { void refreshPlatformHealth(); }, [refreshPlatformHealth]);

  return <section className="platform-settings">
    <header className="ps-hero"><Settings aria-hidden="true" /><div><span>Administration</span><h2>Platform control panel</h2><p>Live state of every KaiMS application service, plus authoritative platform configuration availability.</p></div><button type="button" onClick={() => { void dashboard.refreshProjects(); safety.refresh(); void refreshPlatformHealth(); }} disabled={healthLoading}><RefreshCw aria-hidden="true" /> {healthLoading ? "Checking services" : "Refresh state"}</button></header>
    <section className="ps-service-control" aria-labelledby="service-control-title" aria-busy={healthLoading}>
      <header><div><span>Live platform topology</span><h3 id="service-control-title">Service control panel</h3><p>Each state is observed directly from the service health endpoint. Unreachable services remain visible.</p></div><StatusBadge tone={platformHealth?.status === "healthy" ? "success" : healthError ? "danger" : "warning"}>{healthLoading ? "Checking" : healthError ? "Unavailable" : platformHealth?.status || "Unknown"}</StatusBadge></header>
      <div className="ps-health-summary"><span className="is-total"><Server aria-hidden="true" /><strong>{platformHealth?.summary.total ?? "—"}</strong><small>Total services</small></span><span className="is-healthy"><CheckCircle2 aria-hidden="true" /><strong>{platformHealth?.summary.healthy ?? "—"}</strong><small>Healthy</small></span><span className="is-degraded"><Activity aria-hidden="true" /><strong>{platformHealth?.summary.degraded ?? "—"}</strong><small>Degraded</small></span><span className="is-unavailable"><ShieldAlert aria-hidden="true" /><strong>{platformHealth?.summary.unavailable ?? "—"}</strong><small>Unavailable</small></span></div>
      {healthError ? <p className="ps-health-error" role="alert">Service state could not be loaded: {healthError}</p> : null}
      <div className="ps-service-grid">{platformHealth?.services.map((row) => <article key={row.service} className={`ps-service-card is-${row.status}`}><header><span className="ps-service-state"><i aria-hidden="true" />{row.status}</span><code>{row.status_code ?? "—"}</code></header><h4>{row.service}</h4><p>{row.capability}</p><dl><div><dt>Latency</dt><dd>{Number.isFinite(row.latency_ms) ? `${row.latency_ms} ms` : "Unavailable"}</dd></div><div><dt>Probe</dt><dd>{row.detail || "No detail returned"}</dd></div></dl></article>)}</div>
      <footer><span>Last observed: <strong>{platformHealth?.observed_at ? formatUtcTimestamp(platformHealth.observed_at) : "Not yet observed"}</strong></span><button type="button" onClick={() => void refreshPlatformHealth()} disabled={healthLoading}><RefreshCw aria-hidden="true" /> Probe all services</button></footer>
    </section>
    <div className="ps-grid">
      <main>
        <section className="ps-section"><header><div><span>Operational defaults</span><h3>Workspace context</h3></div><StatusBadge tone="info">User scoped</StatusBadge></header><label>Default project<select value={dashboard.selectedProject} onChange={(event) => dashboard.selectProject(event.target.value)}>{dashboard.observedProjects.map((project) => <option key={project} value={project}>{project}</option>)}</select><small>This changes the current user workspace; it does not change backend safety policy.</small></label><div className="ps-preference-note"><Bell aria-hidden="true" /><span><strong>Display and notification preferences</strong><small>Theme and density are available from the user menu. Durable delivery preferences require a per-user backend contract.</small></span></div></section>
        <section className="ps-section"><header><div><span>Platform capabilities</span><h3>Authoritative service state</h3></div></header><div className="ps-health-list"><ServiceHealth service="Gateway policy telemetry" status={gatewayHealthy ? "Healthy" : "Unavailable"} detail={safety.summaryError || `${safety.events.length} recent event(s)`} /><ServiceHealth service="Realtime landing pad" status={landingHealthy ? "Healthy" : "Unavailable"} detail={safety.landingError || `${safety.landingRows.length} recent signal(s)`} /><ServiceHealth service="User administration" status={admin.authenticated ? "Available" : "Unavailable"} detail={admin.authenticated ? `${admin.users.length} user record(s) loaded` : admin.sessionError || "Administrator session required"} /></div></section>
      </main>
      <aside>
        <section className="ps-section ps-security"><header><ShieldCheck aria-hidden="true" /><div><span>Security posture</span><h3>Protected configuration</h3></div></header><ul><li><KeyRound aria-hidden="true" /><span><strong>Credentials remain concealed</strong><small>Connection secrets are never displayed after save.</small></span></li><li><Database aria-hidden="true" /><span><strong>Backend policy is authoritative</strong><small>Frontend preferences cannot weaken execution controls.</small></span></li><li><ShieldCheck aria-hidden="true" /><span><strong>Role-gated administration</strong><small>This route is available only to administrators.</small></span></li></ul></section>
        <section className="ps-section ps-unavailable"><span>Configuration APIs</span><h3>Advanced platform mutation unavailable</h3><p>Global retention, delivery, identity-provider, and autonomy defaults need authenticated backend contracts. KaiMS does not present local-only controls as saved settings.</p><button type="button" disabled>Backend contract required</button></section>
      </aside>
    </div>
  </section>;
}
