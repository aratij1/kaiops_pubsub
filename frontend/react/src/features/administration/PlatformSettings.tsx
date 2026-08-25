import { Bell, Database, KeyRound, RefreshCw, Settings, ShieldCheck } from "lucide-react";

import { useRouteRuntime } from "../../app/routeRuntime";
import { ServiceHealth, StatusBadge } from "../../components/design-system";
import "./PlatformSettings.css";

export default function PlatformSettings() {
  const { dashboard, safety, admin } = useRouteRuntime();
  const gatewayHealthy = !safety.summaryError;
  const landingHealthy = !safety.landingError;

  return <section className="platform-settings">
    <header className="ps-hero"><Settings aria-hidden="true" /><div><span>Administration</span><h2>Platform settings</h2><p>Authoritative platform context and configuration availability. Secrets and access tokens are never rendered.</p></div><button type="button" onClick={() => { void dashboard.refreshProjects(); safety.refresh(); }}><RefreshCw aria-hidden="true" /> Refresh state</button></header>
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
