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
  // Required for newly discovered resources. Legacy rows may remain null
  // until authoritative connection reconciliation succeeds.
  connection_id: string | null;
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
  readiness: ReadinessRow[];
};

export type ReadinessGap = { dimension: string; score: number; recommendation: string };
export type ReadinessRow = { project_id: string; service_id: string; environment: string; readiness_state: string; overall_score: number; autonomy_score?: number; scores: Record<string, number>; dimensions?: Record<string, number>; gaps?: ReadinessGap[] };

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

async function requestJson<T>(accessToken: string, url: string, init?: RequestInit): Promise<T> {
  const token = accessToken.trim();
  if (!token) throw new Error("Not authenticated");
  const response = await fetch(`/api-gateway${url}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with ${response.status}`);
  }
  const payload = await response.json() as T | { data?: T };
  if (payload && typeof payload === "object" && "data" in payload && payload.data !== undefined) {
    return payload.data;
  }
  return payload as T;
}

export function listConnections(accessToken: string, projectId?: string, signal?: AbortSignal) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  const query = params.toString();
  return requestJson<RowsResponse<CloudConnection>>(
    accessToken,
    `/cloud-ops/connections${query ? `?${query}` : ""}`,
    { signal },
  ).then((data) => data.rows);
}

export function createSimulatorConnection(accessToken: string, projectId: string, name: string) {
  return requestJson<ConnectionResponse>(accessToken, "/cloud-ops/connections", {
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

export function validateConnection(accessToken: string, connectionId: string, signal?: AbortSignal) {
  return requestJson<{ status: string; checks: unknown[]; warnings: string[]; errors: string[] }>(
    accessToken,
    `/cloud-ops/connections/${encodeURIComponent(connectionId)}/validate`,
    { method: "POST", body: JSON.stringify({}), signal },
  );
}

export function discoverConnection(accessToken: string, connectionId: string, projectId: string, serviceId = "checkout-api", environment = "prod", signal?: AbortSignal) {
  return requestJson<{ run_id: string; status: string; resources: CloudResource[]; relationships: unknown[] }>(
    accessToken,
    `/cloud-ops/connections/${encodeURIComponent(connectionId)}/discover`,
    { method: "POST", body: JSON.stringify({ project_id: projectId, service_id: serviceId, environment }), signal },
  );
}

export function listResources(accessToken: string, projectId?: string, serviceId?: string, environment?: string) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (serviceId) params.set("service_id", serviceId);
  if (environment) params.set("environment", environment);
  const query = params.toString();
  return requestJson<RowsResponse<CloudResource>>(accessToken, `/cloud-ops/resources${query ? `?${query}` : ""}`).then((data) => data.rows);
}

export function service360(accessToken: string, projectId: string, serviceId: string, environment?: string) {
  const params = new URLSearchParams({ project_id: projectId });
  if (environment) params.set("environment", environment);
  return requestJson<Service360>(accessToken, `/cloud-ops/services/${encodeURIComponent(serviceId)}/360?${params.toString()}`);
}

export function serviceTopology(accessToken: string, projectId: string, serviceId: string, environment?: string) {
  const params = new URLSearchParams({ project_id: projectId });
  if (environment) params.set("environment", environment);
  return requestJson<{ nodes: CloudResource[]; edges: Array<Record<string, unknown>> }>(accessToken, `/cloud-ops/services/${encodeURIComponent(serviceId)}/topology?${params.toString()}`);
}

export function operationsCockpit(accessToken: string, projectId?: string, environment?: string) {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (environment) params.set("environment", environment);
  const query = params.toString();
  return requestJson<CockpitSummary>(accessToken, `/cloud-ops/cockpit${query ? `?${query}` : ""}`);
}

export function onboardingTemplates(accessToken: string) {
  return requestJson<{ templates: OnboardingTemplate[] }>(accessToken, "/cloud-ops/onboarding/templates").then((data) => data.templates);
}

export function saveOnboardingProfile(accessToken: string, serviceId: string, profile: OnboardingProfile) {
  return requestJson<{ profile: OnboardingProfile & { onboarding_state: string }; readiness: { state: string; overall_score: number; scores: Record<string, number> } }>(
    accessToken,
    `/cloud-ops/services/${encodeURIComponent(serviceId)}/onboarding`,
    { method: "PUT", body: JSON.stringify(profile) },
  );
}

export function recalculateReadiness(accessToken: string, projectId: string, serviceId: string, environment = "prod") {
  return requestJson<{ state: string; overall_score: number; scores: Record<string, number> }>(
    accessToken,
    `/cloud-ops/services/${encodeURIComponent(serviceId)}/readiness/recalculate`,
    { method: "POST", body: JSON.stringify({ project_id: projectId, environment }) },
  );
}

export function compileCloudPlan(accessToken: string, input: { project_id: string; service_id: string; environment: string; intent: string; action_type: string; resource_id: string; rollback_action: string }) {
  return requestJson<{ plan: CompiledPlan }>(accessToken, "/cloud-ops/plans/compile", {
    method: "POST",
    body: JSON.stringify({
      project_id: input.project_id, service_id: input.service_id, environment: input.environment, intent: input.intent,
      actions: [{ action_type: input.action_type, resource_id: input.resource_id, parameters: {}, rollback_action: input.rollback_action || null }],
    }),
  }).then((data) => data.plan);
}

export function simulateCloudPlan(accessToken: string, planId: string) {
  return requestJson<{ simulation: PlanSimulation }>(accessToken, `/cloud-ops/plans/${encodeURIComponent(planId)}/simulate`, {
    method: "POST", body: JSON.stringify({}),
  }).then((data) => data.simulation);
}

export function approveCloudPlan(accessToken: string, plan: CompiledPlan, reason: string) {
  return requestJson<{ approval: { id: string; decision: string; checksum: string } }>(accessToken, `/cloud-ops/plans/${encodeURIComponent(plan.id)}/approval`, {
    method: "POST", body: JSON.stringify({ checksum: plan.checksum, decision: "approved", reason }),
  }).then((data) => data.approval);
}

export function executeCloudPlan(accessToken: string, planId: string) {
  return requestJson<{ execution: CloudPlanExecution; reused: boolean }>(accessToken, `/cloud-ops/plans/${encodeURIComponent(planId)}/execute`, {
    method: "POST", body: JSON.stringify({}),
  });
}

export function rollbackCloudExecution(accessToken: string, executionId: string) {
  return requestJson<{ execution: CloudPlanExecution; reused: boolean }>(accessToken, `/cloud-ops/executions/${encodeURIComponent(executionId)}/rollback`, {
    method: "POST", body: JSON.stringify({}),
  });
}

export function saveExecutionPolicy(accessToken: string, projectId: string, environment: string, actionType: string) {
  return requestJson<{ policy: Record<string, unknown> }>(accessToken, "/cloud-ops/governance/policy", {
    method: "PUT", body: JSON.stringify({ project_id: projectId, environment, allowed_providers: ["simulator"], allowed_actions: [actionType], maximum_risk: "high", require_rollback: true, require_maintenance_window: true, enabled: true }),
  });
}

export function openMaintenanceWindow(accessToken: string, projectId: string, environment: string, reason: string) {
  const startsAt = new Date();
  const endsAt = new Date(startsAt.getTime() + 30 * 60 * 1000);
  return requestJson<{ window: { id: string; starts_at: string; ends_at: string } }>(accessToken, "/cloud-ops/governance/maintenance-windows", {
    method: "POST", body: JSON.stringify({ project_id: projectId, environment, starts_at: startsAt.toISOString(), ends_at: endsAt.toISOString(), reason }),
  });
}

export function recoverExecutionLeases(accessToken: string) {
  return requestJson<{ recovered: number }>(accessToken, "/cloud-ops/governance/leases/recover", { method: "POST", body: JSON.stringify({}) });
}

export type CloudProviderStatus = { provider: string; registered: boolean; execution_enabled: boolean; health_status: string; connector_version?: string; write_operations: string[]; kill_switch_engaged?: boolean; canary_target_count?: number };

export function listCloudProviderStatus(accessToken: string) {
  return requestJson<{ providers: CloudProviderStatus[] }>(accessToken, "/cloud-ops/providers/status").then((data) => data.providers);
}
