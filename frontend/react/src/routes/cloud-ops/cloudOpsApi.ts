export type CloudConnection = {
  id: string;
  tenant_id: string;
  project_id: string;
  connection_name: string;
  provider_type: string;
  status: string;
  credential_ref?: string;
  allowed_regions: string[];
  read_capability: boolean;
  write_capability: boolean;
  connection_owner: string;
  created_at?: string;
  last_health_check_at?: string;
  last_discovery_at?: string;
};

export type CloudResource = {
  id: string;
  tenant_id: string;
  project_id: string;
  connection_id: string;
  provider: string;
  provider_resource_id: string;
  resource_type: string;
  display_name: string;
  region?: string | null;
  environment?: string | null;
  service_id?: string | null;
  status: string;
  tags?: Record<string, unknown>;
  attributes?: Record<string, unknown>;
  discovered_at?: string;
};

export type Service360 = {
  tenant_id: string;
  project_id: string;
  service_id: string;
  environment?: string | null;
  health: Record<string, number>;
  readiness: Record<string, unknown>;
  readiness_state: string;
  resources: CloudResource[];
  relationships: Array<Record<string, unknown>>;
};

export type OnboardingTemplate = {
  id: string;
  label: string;
  resource_types: string[];
  recommended_telemetry: string[];
  recommended_controls: string[];
};

export type OnboardingProfile = {
  project_id: string;
  service_id: string;
  environment: string;
  template_id: string;
  business_criticality: string;
  owners: string[];
  support_groups: string[];
  connection_ids: string[];
  monitoring_sources: string[];
  log_sources: string[];
  metric_sources: string[];
  trace_sources: string[];
  event_sources: string[];
  slos: Array<Record<string, unknown>>;
  business_kpis: Array<Record<string, unknown>>;
  change_sources: string[];
  knowledge_refs: string[];
  diagnostic_capabilities: string[];
  remediation_capabilities: string[];
  validation_rules: string[];
  escalation_policies: string[];
  hitl_policy: Record<string, unknown>;
  dependencies: string[];
  resource_ids: string[];
  topology: Array<Record<string, unknown>>;
  approved_capabilities: string[];
  prohibited_operations: string[];
  maintenance_windows: Array<Record<string, unknown>>;
  change_freeze_periods: Array<Record<string, unknown>>;
  rollback_procedures: string[];
  runbook_owners: string[];
  metadata: Record<string, unknown>;
};

export type CockpitSummary = {
  resource_count: number;
  service_count: number;
  health: Record<string, number>;
  by_provider: Record<string, number>;
  by_environment: Record<string, number>;
  readiness: Array<{ project_id: string; service_id: string; environment: string; readiness_state: string; overall_score: number; scores: Record<string, number> }>;
};

export type CompiledPlan = {
  id: string; project_id: string; service_id: string; environment: string; intent: string;
  actions: Array<{ action_type: string; resource_id: string; parameters: Record<string, unknown>; rollback_action?: string | null }>;
  risk_level: string; requires_approval: boolean; checksum: string; status: string;
};

export type PlanSimulation = {
  id: string; plan_id: string; verdict: "passed" | "blocked";
  gates: Array<{ gate: string; passed: boolean; message: string }>;
};

export type CloudPlanExecution = {
  id: string; plan_id: string; checksum: string; idempotency_key: string; provider: string;
  status: string; action_results: Array<Record<string, unknown>>; validation: Record<string, unknown>; error?: string | null;
};

type RowsResponse<T> = { rows: T[]; count: number };
type ConnectionResponse = { connection: CloudConnection };

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function listConnections(projectId?: string) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  const query = params.toString();
  return requestJson<RowsResponse<CloudConnection>>(`/cloud-ops/connections${query ? `?${query}` : ""}`).then((data) => data.rows);
}

export function createSimulatorConnection(projectId: string, name: string) {
  return requestJson<ConnectionResponse>("/cloud-ops/connections", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      connection_name: name,
      provider_type: "simulator",
      credential_ref: "simulator://local/read-only",
      connection_owner: "cloud-ops-admin-ui",
      read_capability: true,
      write_capability: false,
      allowed_regions: ["global"],
      resource_filters: {},
      discovery_scope: {},
    }),
  }).then((data) => data.connection);
}

export function validateConnection(connectionId: string) {
  return requestJson<{ status: string; checks: unknown[]; warnings: string[]; errors: string[] }>(
    `/cloud-ops/connections/${encodeURIComponent(connectionId)}/validate`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function discoverConnection(connectionId: string, projectId: string, serviceId = "checkout-api", environment = "prod") {
  return requestJson<{ run_id: string; status: string; resources: CloudResource[]; relationships: unknown[] }>(
    `/cloud-ops/connections/${encodeURIComponent(connectionId)}/discover`,
    { method: "POST", body: JSON.stringify({ project_id: projectId, service_id: serviceId, environment }) },
  );
}

export function listResources(projectId?: string, serviceId?: string, environment?: string) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (serviceId) params.set("service_id", serviceId);
  if (environment) params.set("environment", environment);
  const query = params.toString();
  return requestJson<RowsResponse<CloudResource>>(`/cloud-ops/resources${query ? `?${query}` : ""}`).then((data) => data.rows);
}

export function service360(projectId: string, serviceId: string, environment?: string) {
  const params = new URLSearchParams({ project_id: projectId });
  if (environment) params.set("environment", environment);
  return requestJson<Service360>(`/cloud-ops/services/${encodeURIComponent(serviceId)}/360?${params.toString()}`);
}

export function serviceTopology(projectId: string, serviceId: string, environment?: string) {
  const params = new URLSearchParams({ project_id: projectId });
  if (environment) params.set("environment", environment);
  return requestJson<{ nodes: CloudResource[]; edges: Array<Record<string, unknown>> }>(`/cloud-ops/services/${encodeURIComponent(serviceId)}/topology?${params.toString()}`);
}

export function operationsCockpit(projectId?: string, environment?: string) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (environment) params.set("environment", environment);
  const query = params.toString();
  return requestJson<CockpitSummary>(`/cloud-ops/cockpit${query ? `?${query}` : ""}`);
}

export function onboardingTemplates() {
  return requestJson<{ templates: OnboardingTemplate[] }>("/cloud-ops/onboarding/templates").then((data) => data.templates);
}

export function saveOnboardingProfile(serviceId: string, profile: OnboardingProfile) {
  return requestJson<{ profile: OnboardingProfile & { onboarding_state: string }; readiness: { state: string; overall_score: number; scores: Record<string, number> } }>(
    `/cloud-ops/services/${encodeURIComponent(serviceId)}/onboarding`,
    { method: "PUT", body: JSON.stringify(profile) },
  );
}

export function recalculateReadiness(projectId: string, serviceId: string, environment = "prod") {
  return requestJson<{ state: string; overall_score: number; scores: Record<string, number> }>(
    `/cloud-ops/services/${encodeURIComponent(serviceId)}/readiness/recalculate`,
    { method: "POST", body: JSON.stringify({ project_id: projectId, environment }) },
  );
}

export function compileCloudPlan(input: { project_id: string; service_id: string; environment: string; intent: string; action_type: string; resource_id: string; rollback_action: string }) {
  return requestJson<{ plan: CompiledPlan }>("/cloud-ops/plans/compile", {
    method: "POST",
    body: JSON.stringify({
      project_id: input.project_id, service_id: input.service_id, environment: input.environment, intent: input.intent,
      actions: [{ action_type: input.action_type, resource_id: input.resource_id, parameters: {}, rollback_action: input.rollback_action || null }],
    }),
  }).then((data) => data.plan);
}

export function simulateCloudPlan(planId: string) {
  return requestJson<{ simulation: PlanSimulation }>(`/cloud-ops/plans/${encodeURIComponent(planId)}/simulate`, {
    method: "POST", body: JSON.stringify({}),
  }).then((data) => data.simulation);
}

export function approveCloudPlan(plan: CompiledPlan, reason: string) {
  return requestJson<{ approval: { id: string; decision: string; checksum: string } }>(`/cloud-ops/plans/${encodeURIComponent(plan.id)}/approval`, {
    method: "POST", body: JSON.stringify({ checksum: plan.checksum, decision: "approved", reason }),
  }).then((data) => data.approval);
}

export function executeCloudPlan(planId: string) {
  return requestJson<{ execution: CloudPlanExecution; reused: boolean }>(`/cloud-ops/plans/${encodeURIComponent(planId)}/execute`, {
    method: "POST", body: JSON.stringify({}),
  });
}

export function rollbackCloudExecution(executionId: string) {
  return requestJson<{ execution: CloudPlanExecution; reused: boolean }>(`/cloud-ops/executions/${encodeURIComponent(executionId)}/rollback`, {
    method: "POST", body: JSON.stringify({}),
  });
}

export function saveExecutionPolicy(projectId: string, environment: string, actionType: string) {
  return requestJson<{ policy: Record<string, unknown> }>("/cloud-ops/governance/policy", {
    method: "PUT", body: JSON.stringify({ project_id: projectId, environment, allowed_providers: ["simulator"], allowed_actions: [actionType], maximum_risk: "high", require_rollback: true, require_maintenance_window: true, enabled: true }),
  });
}

export function openMaintenanceWindow(projectId: string, environment: string, reason: string) {
  const startsAt = new Date();
  const endsAt = new Date(startsAt.getTime() + 30 * 60 * 1000);
  return requestJson<{ window: { id: string; starts_at: string; ends_at: string } }>("/cloud-ops/governance/maintenance-windows", {
    method: "POST", body: JSON.stringify({ project_id: projectId, environment, starts_at: startsAt.toISOString(), ends_at: endsAt.toISOString(), reason }),
  });
}

export function recoverExecutionLeases() {
  return requestJson<{ recovered: number }>("/cloud-ops/governance/leases/recover", { method: "POST", body: JSON.stringify({}) });
}

export type CloudProviderStatus = { provider: string; registered: boolean; execution_enabled: boolean; health_status: string; connector_version?: string; write_operations: string[]; kill_switch_engaged?: boolean; canary_target_count?: number };

export function listCloudProviderStatus() {
  return requestJson<{ providers: CloudProviderStatus[] }>("/cloud-ops/providers/status").then((data) => data.providers);
}
