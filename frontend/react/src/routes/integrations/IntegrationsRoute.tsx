import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, RefreshCw, X } from "lucide-react";
import { useRouteRuntime } from "../../app/routeRuntime";
import { applicationKeys, applicationsQueryOptions, createApplication, updateApplication } from "../../services/applications";
import type { Application, ApplicationUpdate, NewApplication } from "../../schemas/applications";

const initialForm: NewApplication = { tenant_id: "default", name: "", owner_team: "platform-ops", owner_email: null, environment: "prod", namespace: "default", region: "us-east-1", technology: "python-fastapi", metrics_endpoint: "http://api-gateway:8000/metrics", monitoring_platform: "prometheus", labels: { security: "internal", compliance: "sox", workload_kind: "Deployment" } };
const labelsToText = (labels: unknown) => labels && typeof labels === "object" ? Object.entries(labels).map(([key, value]) => `${key}=${String(value)}`).join(",") : "";
const parseLabels = (value: string) => Object.fromEntries(value.split(",").map((entry) => entry.trim()).filter(Boolean).map((entry) => { const [key, ...parts] = entry.split("="); return [key.trim(), parts.join("=").trim()]; }).filter(([key]) => key));
const deploymentProviders: Record<string, string> = { cloud_agnostic: "cloud-agnostic", on_prem: "on-prem", private_cloud: "private-cloud", aws_cloud: "aws", azure_cloud: "azure", gcp_cloud: "gcp" };

export default function IntegrationsRoute() {
  const { session } = useRouteRuntime();
  const queryClient = useQueryClient();
  const applications = useQuery(applicationsQueryOptions(session.accessToken));
  const [form, setForm] = useState<NewApplication>(initialForm);
  const [labelsText, setLabelsText] = useState(labelsToText(initialForm.labels));
  const [deploymentMode, setDeploymentMode] = useState("cloud_agnostic");
  const [editing, setEditing] = useState<Application | null>(null);
  const mutation = useMutation({
    mutationKey: ["applications", editing ? "update" : "create"],
    mutationFn: (payload: NewApplication) => editing
      ? updateApplication(session.accessToken, String(editing.id), { ...payload, status: editing.status || "registered" } as ApplicationUpdate)
      : createApplication(session.accessToken, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: applicationKeys.all });
      setEditing(null);
      setForm({ ...initialForm, name: "", owner_email: null });
      setLabelsText(labelsToText(initialForm.labels));
      setDeploymentMode("cloud_agnostic");
    },
  });
  const update = (name: keyof NewApplication, value: string) => setForm((current) => ({ ...current, [name]: value }));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate({ ...form, labels: { ...parseLabels(labelsText), deployment_mode: deploymentMode, cloud_provider: deploymentProviders[deploymentMode] || "cloud-agnostic" } });
  };
  const edit = (row: Application) => {
    setEditing(row);
    setForm({
      tenant_id: row.tenant_id || "default", name: row.name, owner_team: row.owner_team || "platform-ops", owner_email: row.owner_email || null,
      environment: row.environment === "dev" || row.environment === "staging" ? row.environment : "prod", namespace: row.namespace || "default",
      region: row.region || "us-east-1", technology: row.technology || "unknown", metrics_endpoint: row.metrics_endpoint || "",
      monitoring_platform: String(row.monitoring_platform || "prometheus"), labels: typeof row.labels === "object" && row.labels ? row.labels as Record<string, string> : {},
    });
    setLabelsText(labelsToText(row.labels));
    const labels = row.labels && typeof row.labels === "object" ? row.labels as Record<string, unknown> : {};
    setDeploymentMode(String(labels.deployment_mode || "cloud_agnostic"));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const cancel = () => { setEditing(null); setForm(initialForm); setLabelsText(labelsToText(initialForm.labels)); setDeploymentMode("cloud_agnostic"); mutation.reset(); };

  return <section className="grid single-col">
    <article className="panel">
      <div className="panel-head"><div><h2>{editing ? `Edit ${editing.name}` : "Integrations & Monitoring"}</h2><p>{editing ? "Update the monitoring target and application metadata." : "Register an application and start the real discovery, validation, rules, Prometheus, and dashboard onboarding chain."}</p></div>{editing ? <button className="icon-button" type="button" title="Cancel editing" aria-label="Cancel editing" onClick={cancel}><X size={17} /></button> : null}</div>
      <form className="form" onSubmit={submit}><div className="filter-grid">{(["tenant_id", "name", "owner_team", "owner_email"] as const).map((name) => <label key={name}>{name.replaceAll("_", " ")}<input value={String(form[name] || "")} onChange={(event) => update(name, event.target.value)} required={name !== "owner_email"} /></label>)}</div><div className="filter-grid"><label>Environment<select value={form.environment} onChange={(event) => update("environment", event.target.value)}><option value="dev">dev</option><option value="staging">staging</option><option value="prod">prod</option></select></label><label>Deployment model<select value={deploymentMode} onChange={(event) => setDeploymentMode(event.target.value)}><option value="cloud_agnostic">Cloud Agnostic</option><option value="on_prem">On-premises</option><option value="private_cloud">Private cloud</option><option value="aws_cloud">AWS</option><option value="azure_cloud">Azure</option><option value="gcp_cloud">Google Cloud</option></select><span className="field-hint">Cloud Agnostic supports portable deployment across public cloud, private cloud, and on-premises environments.</span></label>{(["namespace", "region", "technology"] as const).map((name) => <label key={name}>{name}<input value={form[name]} onChange={(event) => update(name, event.target.value)} required /></label>)}</div><label>Metrics Endpoint<input value={form.metrics_endpoint} onChange={(event) => update("metrics_endpoint", event.target.value)} required /></label><label>Labels (comma-separated key=value)<input value={labelsText} onChange={(event) => setLabelsText(event.target.value)} /></label><div className="button-row"><button className="button-primary" type="submit" disabled={mutation.isPending}>{mutation.isPending ? "Saving..." : editing ? "Save Changes" : "Register Application"}</button>{editing ? <button className="button-secondary" type="button" onClick={cancel}>Cancel</button> : null}</div></form>
      {mutation.error ? <p className="error">{mutation.error.message}</p> : null}{mutation.isSuccess ? <p className="subtitle">Application monitoring configuration was saved.</p> : null}
    </article>
    <article className="panel"><div className="panel-head"><h3>Configured Monitoring Integrations</h3><button className="icon-button" title="Refresh integrations" aria-label="Refresh integrations" onClick={() => applications.refetch()} disabled={applications.isFetching}><RefreshCw size={17} /></button></div><div className="table-wrap"><table><thead><tr><th>Application</th><th>Endpoint</th><th>Environment</th><th>Status</th><th>Action</th></tr></thead><tbody>{applications.data?.map((row) => <tr key={row.id}><td>{row.name}</td><td>{row.metrics_endpoint || "-"}</td><td>{row.environment || "-"}</td><td>{row.status || "-"}</td><td><button className="icon-button" type="button" title={`Edit ${row.name}`} aria-label={`Edit ${row.name}`} onClick={() => edit(row)}><Pencil size={16} /></button></td></tr>)}{!applications.data?.length ? <tr><td colSpan={5}>No monitoring integrations registered.</td></tr> : null}</tbody></table></div></article>
  </section>;
}
