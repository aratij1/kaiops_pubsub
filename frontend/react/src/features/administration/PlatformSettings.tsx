import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Bot,
  Boxes,
  CheckCircle2,
  Database,
  Gauge,
  RefreshCw,
  ShieldCheck,
  Users,
  Zap,
} from "lucide-react";

import { useRouteRuntime } from "../../app/routeRuntime";
import { ReadinessScore, StatusBadge, type StatusTone } from "../../components/design-system";
import "./PlatformSettings.css";

type ProbeKey = "applications" | "queue" | "context" | "models" | "capacity";
type Probe = { payload: unknown; error: string };
type ProbeMap = Record<ProbeKey, Probe>;

const ENDPOINTS: Record<ProbeKey, string> = {
  applications: "/api-gateway/applications",
  queue: "/api-gateway/operations/queue-health",
  context: "/api-gateway/context/strategy",
  models: "/api-gateway/model/providers/status",
  capacity: "/api-gateway/approval/capacity",
};

const EMPTY_PROBES: ProbeMap = {
  applications: { payload: null, error: "" },
  queue: { payload: null, error: "" },
  context: { payload: null, error: "" },
  models: { payload: null, error: "" },
  capacity: { payload: null, error: "" },
};

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function unwrapped(value: unknown): Record<string, unknown> {
  const root = record(value);
  return Object.keys(record(root.data)).length ? record(root.data) : root;
}

function rows(value: unknown): unknown[] {
  const root = unwrapped(value);
  return Array.isArray(root.rows) ? root.rows : Array.isArray(value) ? value : [];
}

function probeTone(error: string, healthy: boolean): StatusTone {
  if (error) return "critical";
  return healthy ? "success" : "warning";
}

export default function PlatformSettings() {
  const { safety, session } = useRouteRuntime();
  const [state, setState] = useState({ loading: false, checkedAt: "", probes: EMPTY_PROBES });

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!session.accessToken) return;
    setState((current) => ({ ...current, loading: true }));
    const headers = { Authorization: `Bearer ${session.accessToken}`, Accept: "application/json" };
    const results = await Promise.all(
      (Object.entries(ENDPOINTS) as [ProbeKey, string][]).map(async ([key, endpoint]) => {
        try {
          const response = await fetch(endpoint, { headers, signal });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return [key, { payload: await response.json() as unknown, error: "" }] as const;
        } catch (error) {
          if (signal?.aborted) return [key, { payload: null, error: "Cancelled" }] as const;
          return [key, { payload: null, error: String((error as Error).message || error) }] as const;
        }
      }),
    );
    if (signal?.aborted) return;
    const probes = { ...EMPTY_PROBES };
    results.forEach(([key, result]) => { probes[key] = result; });
    setState({ loading: false, checkedAt: new Date().toISOString(), probes });
  }, [session.accessToken]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const interval = window.setInterval(() => { void refresh(); }, 45_000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [refresh]);

  const view = useMemo(() => {
    const applicationRows = rows(state.probes.applications.payload);
    const capacityRows = rows(state.probes.capacity.payload).map(record);
    const activeReviewers = capacityRows.filter((item) => item.active !== false).length;
    const queue = unwrapped(state.probes.queue.payload);
    const context = unwrapped(state.probes.context.payload);
    const models = unwrapped(state.probes.models.payload);
    const providerRows = Object.entries(record(models.providers)).map(([name, value]) => {
      const provider = record(value);
      return {
        name,
        configured: Boolean(provider.configured),
        healthy: Boolean(provider.healthy),
        circuitOpen: Boolean(provider.circuit_open),
      };
    });
    const configuredProviders = providerRows.filter((provider) => Boolean(provider.configured));
    const healthyProviders = configuredProviders.filter((provider) => provider.healthy && !provider.circuitOpen);
    const queueHealthy = Boolean(queue.healthy);
    const contextReady = String(context.default || "").length > 0 && Array.isArray(context.supported);
    const aiReady = configuredProviders.length > 0 && healthyProviders.length === configuredProviders.length;
    const gatewayHealthy = !safety.summaryError;
    const scores = {
      intake: state.probes.queue.error ? 0 : queueHealthy ? 100 : 55,
      catalog: state.probes.applications.error ? 0 : applicationRows.length ? 100 : 60,
      context: state.probes.context.error ? 0 : contextReady ? 100 : 55,
      ai: state.probes.models.error ? 0 : aiReady ? 100 : configuredProviders.length ? 55 : 35,
      governance: state.probes.capacity.error ? 35 : activeReviewers ? 100 : 70,
    };
    const readiness = Math.round(Object.values(scores).reduce((total, score) => total + score, 0) / Object.keys(scores).length);
    const failures = Object.values(state.probes).filter((probe) => probe.error).length;
    return {
      applicationRows,
      activeReviewers,
      queue,
      context,
      configuredProviders,
      healthyProviders,
      queueHealthy,
      contextReady,
      aiReady,
      gatewayHealthy,
      scores,
      readiness,
      failures,
    };
  }, [safety.summaryError, state.probes]);

  const checkedAt = state.checkedAt
    ? new Date(state.checkedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "Not checked";

  const capabilities = [
    { label: "Signal intake", score: view.scores.intake },
    { label: "Service catalog", score: view.scores.catalog },
    { label: "Context intelligence", score: view.scores.context },
    { label: "AI reasoning", score: view.scores.ai },
    { label: "Governed action", score: view.scores.governance },
  ];

  const flow = [
    ["Detect", "Signals and telemetry"],
    ["Correlate", "Unified incident"],
    ["Enrich", "Durable context"],
    ["Reason", "Evidence-backed RCA"],
    ["Govern", "Policy and approval"],
    ["Verify", "Outcome and learning"],
  ];

  return <section className="platform-control-plane">
    <header className="pcp-hero">
      <div className="pcp-hero-copy">
        <span className="pcp-eyebrow"><Gauge aria-hidden="true" /> Wave 9 control plane</span>
        <h2>Operate the platform as one system.</h2>
        <p>Live readiness across telemetry, context, AI reasoning, human governance, and safe execution—with every status tied to a backend signal.</p>
        <div className="pcp-hero-meta">
          <StatusBadge tone={view.failures ? "warning" : "success"}>{view.failures ? `${view.failures} probe${view.failures === 1 ? "" : "s"} need attention` : "Control plane connected"}</StatusBadge>
          <span>Last checked {checkedAt}</span>
        </div>
      </div>
      <div className="pcp-score" style={{ "--pcp-score": `${view.readiness * 3.6}deg` } as CSSProperties}>
        <div><strong>{view.readiness}%</strong><span>readiness</span></div>
      </div>
      <button type="button" className="pcp-refresh" onClick={() => { void refresh(); }} disabled={state.loading}>
        <RefreshCw aria-hidden="true" className={state.loading ? "is-spinning" : ""} />
        {state.loading ? "Checking" : "Refresh"}
      </button>
    </header>

    <section className="pcp-kpis" aria-label="Platform readiness summary">
      <article><Boxes aria-hidden="true" /><div><span>Observed estate</span><strong>{view.applicationRows.length}</strong><small>registered application{view.applicationRows.length === 1 ? "" : "s"}</small></div></article>
      <article><Activity aria-hidden="true" /><div><span>Event backbone</span><strong>{view.queueHealthy ? "Ready" : "Attention"}</strong><small>{Number(view.queue.messages || 0)} queued · {Number(view.queue.unacknowledged || 0)} in flight</small></div></article>
      <article><Bot aria-hidden="true" /><div><span>AI providers</span><strong>{view.healthyProviders.length}/{view.configuredProviders.length}</strong><small>configured providers healthy</small></div></article>
      <article><Users aria-hidden="true" /><div><span>Decision capacity</span><strong>{view.activeReviewers}</strong><small>active reviewer profile{view.activeReviewers === 1 ? "" : "s"}</small></div></article>
    </section>

    <section className="pcp-flow" aria-labelledby="pcp-flow-title">
      <header><div><span className="pcp-eyebrow">Operational value stream</span><h3 id="pcp-flow-title">Signal to verified outcome</h3></div><StatusBadge tone="info">Governed by design</StatusBadge></header>
      <ol>{flow.map(([label, detail], index) => <li key={label}><span>{index + 1}</span><div><strong>{label}</strong><small>{detail}</small></div>{index < flow.length - 1 ? <ArrowRight aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}</li>)}</ol>
    </section>

    <div className="pcp-layout">
      <main>
        <section className="pcp-panel pcp-capability-panel">
          <header><div><span className="pcp-eyebrow">Live capability posture</span><h3>What is ready now</h3></div><small>No synthetic green states</small></header>
          <div className="pcp-capability-list">
            <article>
              <span className="pcp-capability-icon"><Activity /></span>
              <div><strong>Telemetry and event intake</strong><p>RabbitMQ queue health, backlog, and consumer flow from the running data plane.</p></div>
              <div className="pcp-capability-state"><StatusBadge tone={probeTone(state.probes.queue.error, view.queueHealthy)}>{state.probes.queue.error || (view.queueHealthy ? "Operational" : String(view.queue.status || "Attention"))}</StatusBadge><small>{Number(view.queue.queues || 0)} queues observed</small></div>
            </article>
            <article>
              <span className="pcp-capability-icon"><Database /></span>
              <div><strong>Durable context intelligence</strong><p>Cache-aside evidence collection with scope, freshness, quality, and conflict controls.</p></div>
              <div className="pcp-capability-state"><StatusBadge tone={probeTone(state.probes.context.error, view.contextReady)}>{state.probes.context.error || (view.contextReady ? `${String(view.context.default)} strategy` : "Needs attention")}</StatusBadge><small>{Array.isArray(view.context.supported) ? `${view.context.supported.length} collection modes` : "Strategy unavailable"}</small></div>
            </article>
            <article>
              <span className="pcp-capability-icon"><Bot /></span>
              <div><strong>AI reasoning and fallback</strong><p>Provider routing, circuit state, and deterministic continuity remain independently observable.</p></div>
              <div className="pcp-capability-state"><StatusBadge tone={probeTone(state.probes.models.error, view.aiReady)}>{state.probes.models.error || (view.aiReady ? "Healthy" : "Fallback available")}</StatusBadge><small>{view.configuredProviders.length} provider{view.configuredProviders.length === 1 ? "" : "s"} configured</small></div>
            </article>
            <article>
              <span className="pcp-capability-icon"><ShieldCheck /></span>
              <div><strong>Governance and execution safety</strong><p>Role gates, approval capacity, immutable plan binding, and backend-authoritative policy.</p></div>
              <div className="pcp-capability-state"><StatusBadge tone={probeTone(state.probes.capacity.error, view.gatewayHealthy)}>{state.probes.capacity.error || (view.gatewayHealthy ? "Enforced" : "Attention")}</StatusBadge><small>{view.activeReviewers ? `${view.activeReviewers} reviewer profiles ready` : "Add reviewer capacity"}</small></div>
            </article>
          </div>
        </section>

        <section className="pcp-panel pcp-foundation">
          <header><div><span className="pcp-eyebrow">Enterprise foundation</span><h3>Designed for production operations</h3></div></header>
          <div>
            <article><Zap /><strong>Actionable operations</strong><p>Move from a correlated incident to evidence, decision, execution, and verification in one workspace.</p></article>
            <article><ShieldCheck /><strong>Human-controlled autonomy</strong><p>Risk and policy decide whether a workflow is autonomous, supervised, approval-gated, or diagnostic-only.</p></article>
            <article><Database /><strong>Auditable evidence</strong><p>Durable context snapshots keep collection quality, sources, fingerprints, expiry, and reuse provenance together.</p></article>
          </div>
        </section>
      </main>

      <aside>
        <section className="pcp-panel pcp-readiness">
          <ReadinessScore score={view.readiness} capabilities={capabilities} />
          <p>Readiness is calculated from five live control-plane probes, not a hard-coded product score.</p>
        </section>
        <section className="pcp-panel pcp-actions">
          <header><div><span className="pcp-eyebrow">Platform workspaces</span><h3>Configure and govern</h3></div></header>
          <Link to="/cloud-ops/connections"><span><strong>Integrations</strong><small>Provider-neutral connections</small></span><ArrowRight /></Link>
          <Link to="/applications"><span><strong>Applications</strong><small>Ownership and observability</small></span><ArrowRight /></Link>
          <Link to="/cloud-ops/cockpit"><span><strong>Capabilities</strong><small>Safe automation readiness</small></span><ArrowRight /></Link>
          <Link to="/admin"><span><strong>Access and capacity</strong><small>People, roles, and reviewers</small></span><ArrowRight /></Link>
        </section>
        <section className="pcp-panel pcp-trust">
          <ShieldCheck aria-hidden="true" />
          <div><span className="pcp-eyebrow">Trust boundary</span><h3>Backend policy remains authoritative</h3><p>Credentials are concealed, platform mutations are role-gated, and display preferences cannot weaken execution controls.</p></div>
        </section>
      </aside>
    </div>
  </section>;
}
