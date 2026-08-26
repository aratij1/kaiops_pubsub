import { useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Cloud, Gauge, RefreshCw, ShieldCheck } from "lucide-react";

import { useRouteRuntimeSlice } from "../../app/routeRuntime";
import { approveCloudPlan, compileCloudPlan, executeCloudPlan, listCloudProviderStatus, openMaintenanceWindow, operationsCockpit, recoverExecutionLeases, rollbackCloudExecution, saveExecutionPolicy, simulateCloudPlan, type CloudPlanExecution, type CloudProviderStatus, type CockpitSummary, type CompiledPlan, type PlanSimulation, type ReadinessRow } from "./cloudOpsApi";
import "./CloudOpsRoute.css";

const DIMENSION_LABELS: Record<string, string> = { monitoring: "Monitoring", logs: "Logs", traces: "Traces", topology: "Topology", runbooks: "Runbooks", remediation: "Remediation", validation: "Validation", automation: "Automation", slos: "SLOs" };
const percent = (value: number | undefined) => `${Math.round(Number(value || 0) * 100)}%`;

export function aggregateProjectReadiness(rows: ReadinessRow[]) {
  if (!rows.length) return { operational: 0, autonomy: 0, dimensions: {} as Record<string, number> };
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row.dimensions || {})))];
  const average = (values: number[]) => values.reduce((total, value) => total + value, 0) / values.length;
  return { operational: average(rows.map((row) => Number(row.overall_score || 0))), autonomy: average(rows.map((row) => Number(row.autonomy_score || 0))), dimensions: Object.fromEntries(keys.map((key) => [key, average(rows.map((row) => Number(row.dimensions?.[key] || 0)))])) };
}

export default function OperationsCockpitRoute() {
  const { accessToken } = useRouteRuntimeSlice("session");
  const [projectId, setProjectId] = useState("demo-project");
  const [environment, setEnvironment] = useState("");
  const [summary, setSummary] = useState<CockpitSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [planForm, setPlanForm] = useState({ serviceId: "checkout-api", resourceId: "", intent: "Restore service health", actionType: "restart_kubernetes_deployment", rollbackAction: "restore_previous_replica_set" });
  const [compiledPlan, setCompiledPlan] = useState<CompiledPlan | null>(null);
  const [simulation, setSimulation] = useState<PlanSimulation | null>(null);
  const [approvalReason, setApprovalReason] = useState("");
  const [approved, setApproved] = useState(false);
  const [execution, setExecution] = useState<CloudPlanExecution | null>(null);
  const [governanceStatus, setGovernanceStatus] = useState("");
  const [providerStatus, setProviderStatus] = useState<CloudProviderStatus[]>([]);
  const projectReadiness = aggregateProjectReadiness(summary?.readiness || []);

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      const [cockpit, providers] = await Promise.all([operationsCockpit(accessToken, projectId || undefined, environment || undefined), listCloudProviderStatus(accessToken)]);
      setSummary(cockpit);
      setProviderStatus(providers);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load operations cockpit");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function compileAndSimulate() {
    setBusy(true);
    setError("");
    setSimulation(null);
    setApproved(false);
    setExecution(null);
    try {
      const plan = await compileCloudPlan(accessToken, { project_id: projectId, service_id: planForm.serviceId, environment: environment || "prod", intent: planForm.intent, action_type: planForm.actionType, resource_id: planForm.resourceId, rollback_action: planForm.rollbackAction });
      setCompiledPlan(plan);
      setSimulation(await simulateCloudPlan(accessToken, plan.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to compile and simulate plan");
    } finally {
      setBusy(false);
    }
  }

  async function approveAndResimulate() {
    if (!compiledPlan) return;
    setBusy(true); setError("");
    try {
      await approveCloudPlan(accessToken, compiledPlan, approvalReason);
      setApproved(true);
      setSimulation(await simulateCloudPlan(accessToken, compiledPlan.id));
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to approve plan"); }
    finally { setBusy(false); }
  }

  async function executeApprovedPlan() {
    if (!compiledPlan) return;
    setBusy(true); setError("");
    try { setExecution((await executeCloudPlan(accessToken, compiledPlan.id)).execution); }
    catch (err) { setError(err instanceof Error ? err.message : "Unable to execute plan"); }
    finally { setBusy(false); }
  }

  async function rollbackExecution() {
    if (!execution) return;
    setBusy(true); setError("");
    try { setExecution((await rollbackCloudExecution(accessToken, execution.id)).execution); }
    catch (err) { setError(err instanceof Error ? err.message : "Unable to roll back execution"); }
    finally { setBusy(false); }
  }

  async function configureGovernance() {
    setBusy(true); setError("");
    try {
      await saveExecutionPolicy(accessToken, projectId, environment || "prod", planForm.actionType);
      await openMaintenanceWindow(accessToken, projectId, environment || "prod", "Operator-approved Phase 5 execution window");
      setGovernanceStatus("Policy active · simulator enabled · maintenance window open for 30 minutes");
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to configure governance"); }
    finally { setBusy(false); }
  }

  async function recoverLeases() {
    setBusy(true); setError("");
    try { const result = await recoverExecutionLeases(accessToken); setGovernanceStatus(`${result.recovered} expired execution lease(s) recovered`); }
    catch (err) { setError(err instanceof Error ? err.message : "Unable to recover leases"); }
    finally { setBusy(false); }
  }

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
          <article className="cloud-ops-panel autonomy-dashboard">
            <header><div><h2>Readiness and autonomy</h2><p>Observed configuration and discovery signals only. Missing dimensions stay visible and never become fabricated coverage.</p></div><span className="cloud-ops-badge">{summary.readiness.length} services</span></header>
            {summary.readiness.length ? <section className="project-readiness-summary" aria-label="Project readiness summary"><div className="readiness-score-ring"><strong>{percent(projectReadiness.autonomy)}</strong><span>Autonomy readiness</span></div><div><span className="resource-eyebrow">Project posture</span><h3>{projectId || "All projects"}</h3><p>Operational readiness {percent(projectReadiness.operational)} · across {summary.readiness.length} service scope(s)</p></div><div className="readiness-dimension-strip">{Object.entries(projectReadiness.dimensions).map(([key, value]) => <div key={key}><span><b>{DIMENSION_LABELS[key] || key}</b><small>{percent(value)}</small></span><progress max={1} value={value} aria-label={`${DIMENSION_LABELS[key] || key} ${percent(value)}`} /></div>)}</div></section> : null}
            <div className="readiness-service-grid">{summary.readiness.map((row) => <article className="readiness-service-card" key={`${row.project_id}-${row.service_id}-${row.environment}`}><header><div><h3>{row.service_id}</h3><p>{row.project_id} · {row.environment}</p></div><span className="cloud-ops-badge">{row.readiness_state}</span></header><div className="readiness-score-pair"><span><strong>{percent(row.overall_score)}</strong><small>Operational</small></span><span><strong>{percent(row.autonomy_score)}</strong><small>Autonomy</small></span></div><div className="readiness-dimensions">{Object.entries(row.dimensions || row.scores).map(([key, value]) => <div key={key}><span><b>{DIMENSION_LABELS[key] || key.replaceAll("_", " ")}</b><small>{percent(value)}</small></span><progress max={1} value={value} /></div>)}</div><details className="readiness-gaps"><summary>{row.gaps?.length ? <><AlertTriangle size={15} /> {row.gaps.length} readiness gap(s)</> : <><CheckCircle2 size={15} /> Mandatory signals configured</>}</summary>{row.gaps?.length ? <ul>{row.gaps.map((gap) => <li key={gap.dimension}><ShieldCheck size={15} /><span><strong>{DIMENSION_LABELS[gap.dimension] || gap.dimension} · {percent(gap.score)}</strong><small>{gap.recommendation}</small></span></li>)}</ul> : <p>No configuration gap is reported. Runtime policy gates still apply to every action.</p>}</details></article>)}</div>
            {!summary.readiness.length ? <div className="cloud-ops-empty">No readiness scores yet. Save a service onboarding profile first.</div> : null}
          </article>
        </>
      ) : <div className="cloud-ops-empty">Load cockpit data to see cross-cloud posture.</div>}
      <article className="cloud-ops-panel">
        <header><div><h2>Plan compiler and simulation</h2><p>Compile an immutable action plan against governed inventory, then evaluate safety gates without provider writes.</p></div>{compiledPlan ? <span className="cloud-ops-badge">{compiledPlan.risk_level} risk</span> : null}</header>
        <div className="cloud-ops-toolbar">
          <label><span>Service ID</span><input value={planForm.serviceId} onChange={(event) => setPlanForm((current) => ({ ...current, serviceId: event.target.value }))} /></label>
          <label><span>Governed resource ID</span><input value={planForm.resourceId} onChange={(event) => setPlanForm((current) => ({ ...current, resourceId: event.target.value }))} /></label>
          <label><span>Action capability</span><input value={planForm.actionType} onChange={(event) => setPlanForm((current) => ({ ...current, actionType: event.target.value }))} /></label>
          <label><span>Rollback action</span><input value={planForm.rollbackAction} onChange={(event) => setPlanForm((current) => ({ ...current, rollbackAction: event.target.value }))} /></label>
          <label><span>Intent</span><input value={planForm.intent} onChange={(event) => setPlanForm((current) => ({ ...current, intent: event.target.value }))} /></label>
        </div>
        <button type="button" className="button-primary" onClick={compileAndSimulate} disabled={busy || !projectId || !planForm.serviceId || !planForm.resourceId}>{busy ? "Simulating…" : "Compile and dry-run"}</button>
        {compiledPlan ? <p>Plan <code>{compiledPlan.id}</code> · checksum <code>{compiledPlan.checksum.slice(0, 12)}</code> · {compiledPlan.requires_approval ? "approval required" : "approval not required"}</p> : null}
        {simulation ? <div className="cloud-ops-grid"><article className="cloud-ops-card"><header><h3>Verdict</h3><span className="cloud-ops-badge">{simulation.verdict}</span></header>{simulation.gates.map((gate) => <p key={gate.gate}><strong>{gate.passed ? "Pass" : "Block"}: {gate.gate}</strong><br />{gate.message}</p>)}</article></div> : null}
        {compiledPlan?.requires_approval && !approved ? <div className="cloud-ops-toolbar"><label><span>Approval reason</span><input value={approvalReason} onChange={(event) => setApprovalReason(event.target.value)} /></label><button type="button" className="button-primary" disabled={busy || !approvalReason.trim()} onClick={approveAndResimulate}>Bind approval to checksum</button></div> : null}
        {compiledPlan && simulation?.verdict === "passed" ? <button type="button" className="button-primary" disabled={busy || Boolean(execution)} onClick={executeApprovedPlan}>{execution ? "Execution recorded" : "Execute approved plan"}</button> : null}
        {execution ? <article className="cloud-ops-card"><header><h3>Execution evidence</h3><span className="cloud-ops-badge">{execution.status}</span></header><p>Lease: <code>{execution.idempotency_key}</code></p><p>Post-action validation: {execution.validation.passed === true ? "passed" : "not passed"}</p>{execution.error ? <p className="cloud-ops-error">{execution.error}</p> : null}{execution.status === "succeeded" ? <button type="button" className="button-secondary" disabled={busy} onClick={rollbackExecution}>Run approved rollback</button> : null}</article> : null}
      </article>
      <article className="cloud-ops-panel">
        <header><div><h2>Execution governance</h2><p>Provider enablement, policy-as-code, maintenance windows, short-lived credential sessions, and lease recovery.</p></div><span className="cloud-ops-badge">fail closed</span></header>
        <div className="cloud-ops-grid">{providerStatus.map((provider) => <article className="cloud-ops-card" key={provider.provider}><header><h3>{provider.provider}</h3><span className="cloud-ops-badge">{provider.health_status}</span></header><p>{provider.registered ? provider.connector_version : "Adapter not registered"}</p><p>Execution: {provider.execution_enabled ? "flag enabled" : "disabled"}{provider.kill_switch_engaged ? " · kill switch engaged" : ""}</p><p>{provider.canary_target_count ?? 0} canary target(s) · {provider.write_operations.length} write capability(ies)</p></article>)}</div>
        <div className="button-row"><button type="button" className="button-primary" onClick={configureGovernance} disabled={busy || !projectId}>Apply policy and open window</button><button type="button" className="button-secondary" onClick={recoverLeases} disabled={busy}>Recover expired leases</button></div>
        {governanceStatus ? <p>{governanceStatus}</p> : <p>No execution is allowed until a scoped policy and active maintenance window exist.</p>}
      </article>
    </section>
  );
}
