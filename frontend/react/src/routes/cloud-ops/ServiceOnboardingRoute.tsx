import { useEffect, useMemo, useState } from "react";
import { ClipboardCheck, Save } from "lucide-react";

import { onboardingTemplates, saveOnboardingProfile, type OnboardingTemplate } from "./cloudOpsApi";
import "./CloudOpsRoute.css";

function csv(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

export default function ServiceOnboardingRoute() {
  const [templates, setTemplates] = useState<OnboardingTemplate[]>([]);
  const [projectId, setProjectId] = useState("demo-project");
  const [serviceId, setServiceId] = useState("checkout-api");
  const [environment, setEnvironment] = useState("prod");
  const [templateId, setTemplateId] = useState("kubernetes_microservice");
  const [owners, setOwners] = useState("checkout-oncall@example.com");
  const [supportGroups, setSupportGroups] = useState("checkout-platform");
  const [monitoring, setMonitoring] = useState("prometheus");
  const [logs, setLogs] = useState("opensearch");
  const [knowledge, setKnowledge] = useState("checkout-api-runbook");
  const [diagnostics, setDiagnostics] = useState("read_pod_status, read_database_lag");
  const [remediation, setRemediation] = useState("restart_kubernetes_deployment");
  const [validation, setValidation] = useState("http_health_check, latency_slo");
  const [resourceIds, setResourceIds] = useState("");
  const [prohibited, setProhibited] = useState("delete_resource, expose_public_endpoint");
  const [rollback, setRollback] = useState("rollback_kubernetes_deployment");
  const [runbookOwners, setRunbookOwners] = useState("checkout-platform");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    onboardingTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, []);

  const selectedTemplate = useMemo(() => templates.find((template) => template.id === templateId), [templates, templateId]);

  async function saveProfile() {
    setBusy(true);
    setMessage("");
    try {
      const result = await saveOnboardingProfile(serviceId, {
        project_id: projectId,
        service_id: serviceId,
        environment,
        template_id: templateId,
        business_criticality: "high",
        owners: csv(owners),
        support_groups: csv(supportGroups),
        connection_ids: [],
        monitoring_sources: csv(monitoring),
        log_sources: csv(logs),
        metric_sources: csv(monitoring),
        trace_sources: [],
        event_sources: [],
        slos: [{ name: "availability", target: "99.9" }],
        business_kpis: [],
        change_sources: ["github"],
        knowledge_refs: csv(knowledge),
        diagnostic_capabilities: csv(diagnostics),
        remediation_capabilities: csv(remediation),
        validation_rules: csv(validation),
        escalation_policies: ["primary-oncall"],
        hitl_policy: { required_for: ["production", "high-risk"], role: "HITL_REVIEWER" },
        dependencies: [],
        resource_ids: csv(resourceIds),
        topology: [],
        approved_capabilities: csv(remediation),
        prohibited_operations: csv(prohibited),
        maintenance_windows: [],
        change_freeze_periods: [],
        rollback_procedures: csv(rollback),
        runbook_owners: csv(runbookOwners),
        metadata: { source: "service-onboarding-studio" },
      });
      setMessage(`Saved ${result.profile.onboarding_state}; readiness ${Math.round(result.readiness.overall_score * 100)}.`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Unable to save onboarding profile");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cloud-ops-route" aria-labelledby="service-onboarding-title">
      <article className="cloud-ops-panel">
        <header>
          <div>
            <h2 id="service-onboarding-title">Service onboarding studio</h2>
            <p>Capture the operational contract that turns discovered resources into an incident-ready service.</p>
          </div>
          <button type="button" className="button-primary" onClick={saveProfile} disabled={busy || !projectId || !serviceId}>
            <Save size={16} /> Save profile
          </button>
        </header>
        <div className="cloud-ops-toolbar">
          <label><span>Project ID</span><input value={projectId} onChange={(event) => setProjectId(event.target.value)} /></label>
          <label><span>Service ID</span><input value={serviceId} onChange={(event) => setServiceId(event.target.value)} /></label>
          <label><span>Environment</span><input value={environment} onChange={(event) => setEnvironment(event.target.value)} /></label>
          <label><span>Template</span><select value={templateId} onChange={(event) => setTemplateId(event.target.value)}>{templates.map((template) => <option key={template.id} value={template.id}>{template.label}</option>)}</select></label>
        </div>
      </article>

      {selectedTemplate ? <article className="cloud-ops-card"><header><h3><ClipboardCheck size={18} /> {selectedTemplate.label}</h3></header><p>Resources: {selectedTemplate.resource_types.join(", ")}</p><p>Telemetry: {selectedTemplate.recommended_telemetry.join(", ")}</p><p>Controls: {selectedTemplate.recommended_controls.join(", ")}</p></article> : null}

      <article className="cloud-ops-panel">
        <div className="cloud-ops-grid">
          <label><span>Owners</span><input value={owners} onChange={(event) => setOwners(event.target.value)} /></label>
          <label><span>Support groups</span><input value={supportGroups} onChange={(event) => setSupportGroups(event.target.value)} /></label>
          <label><span>Monitoring sources</span><input value={monitoring} onChange={(event) => setMonitoring(event.target.value)} /></label>
          <label><span>Log sources</span><input value={logs} onChange={(event) => setLogs(event.target.value)} /></label>
          <label><span>Knowledge refs</span><input value={knowledge} onChange={(event) => setKnowledge(event.target.value)} /></label>
          <label><span>Diagnostics</span><input value={diagnostics} onChange={(event) => setDiagnostics(event.target.value)} /></label>
          <label><span>Remediation capabilities</span><input value={remediation} onChange={(event) => setRemediation(event.target.value)} /></label>
          <label><span>Validation rules</span><input value={validation} onChange={(event) => setValidation(event.target.value)} /></label>
          <label><span>Immutable resource IDs</span><input value={resourceIds} onChange={(event) => setResourceIds(event.target.value)} placeholder="provider resource IDs" /></label>
          <label><span>Prohibited operations</span><input value={prohibited} onChange={(event) => setProhibited(event.target.value)} /></label>
          <label><span>Rollback procedures</span><input value={rollback} onChange={(event) => setRollback(event.target.value)} /></label>
          <label><span>Runbook owners</span><input value={runbookOwners} onChange={(event) => setRunbookOwners(event.target.value)} /></label>
        </div>
      </article>
      {message ? <div className={message.startsWith("Saved") ? "cloud-ops-empty" : "cloud-ops-error"} role="status">{message}</div> : null}
    </section>
  );
}
