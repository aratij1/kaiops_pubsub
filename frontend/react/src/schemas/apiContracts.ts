import { z, type ZodTypeAny } from "zod";

import { ApiValidationError } from "../services/apiClient";

const JsonRecord = z.record(z.unknown());
const RecordList = z.array(JsonRecord);
const Identifier = z.union([z.string(), z.number()]);

const User = z.object({
  id: Identifier.optional(),
  username: z.string(),
  role_name: z.string().optional(),
  role: z.union([z.string(), JsonRecord]).optional(),
}).passthrough();

const AuthConfig = z.object({ mode: z.enum(["local", "oidc"]) }).passthrough();
const Login = z.object({ access_token: z.string().min(1), user: User }).passthrough();
const AuthenticatedUser = z.union([User, z.object({ user: User }).passthrough()]);
const Refresh = z.object({ access_token: z.string().min(1) }).passthrough();
const Health = z.object({ status: z.string().min(1) }).passthrough();
const QueueHealth = z.object({
  status: z.string().min(1),
  provider: z.string().min(1),
  healthy: z.boolean(),
  queues: z.number().nonnegative(),
  messages: z.number().nonnegative(),
  ready: z.number().nonnegative(),
  unacknowledged: z.number().nonnegative(),
}).passthrough();
const EvaluationFeedback = z.object({ updated: z.boolean() }).passthrough();
const CollectedContext = z.object({
  incident_id: z.string().uuid(),
  alert: z.object({
    id: z.string().uuid().optional(),
    name: z.string().min(1),
    service: z.string().min(1),
  }).passthrough(),
  related_incidents: z.array(JsonRecord).optional(),
  runbook: z.string().optional(),
  dependency_services: z.array(z.string()).optional(),
  recent_changes: z.array(JsonRecord).optional(),
}).passthrough();
const ResolutionRecommendation = z.object({
  incident_id: z.string().uuid(),
  root_cause: z.string(),
  confidence: z.number().min(0).max(1),
  impact: z.string(),
  recommended_action: z.string(),
  severity: z.string().min(1),
  rationale: z.string(),
  commands: z.array(z.string()).optional(),
  risk: z.string().optional(),
}).passthrough();
const ObjectResponse = z.object({}).passthrough();
const GatewayCollectedContext = z.object({ data: CollectedContext }).passthrough();
const GatewayResolutionRecommendation = z.object({ data: ResolutionRecommendation }).passthrough();
const GatewayObjectResponse = z.object({ data: ObjectResponse }).passthrough();
const AnalysisRegenerationAccepted = z.object({
  request_id: z.string().uuid(),
  status: z.literal("accepted"),
  delivery: z.enum(["published", "queued"]),
  alert_id: z.string().uuid(),
  incident_id: z.string().uuid(),
  previous_recommendation_id: z.string().nullable().optional(),
  expected_recommendation_id: z.string().uuid(),
  analysis_mode: z.enum(["smart", "fresh", "cache"]),
  context_strategy: z.enum(["auto", "realtime", "historical"]),
  poll_after_ms: z.number().int().positive(),
}).passthrough();
const AnalysisRegenerationStatus = z.object({
  request_id: z.string().uuid(),
  incident_id: z.string().uuid(),
  recommendation_id: z.string().uuid().nullable().optional(),
  status: z.enum(["running", "complete", "failed", "timed_out", "superseded"]),
  ready: z.boolean(),
  terminal: z.boolean().optional(),
  retryable: z.boolean().optional(),
  terminal_reason: z.string().nullable().optional(),
}).passthrough();
const ObjectOrList = z.union([ObjectResponse, RecordList]);
const RowsEnvelope = z.union([
  z.object({ rows: z.array(z.unknown()) }).passthrough(),
  z.object({ data: z.object({ rows: z.array(z.unknown()) }).passthrough() }).passthrough(),
  z.array(z.unknown()),
]);
const ContextEnrichmentActivity = z.object({
  schema_version: z.literal("kaiops.context-enrichment.v1"),
  requirements: RecordList,
  jobs: RecordList,
  human_requests: RecordList,
}).passthrough();
const GatewayContextEnrichmentActivity = z.union([
  ContextEnrichmentActivity,
  z.object({ data: ContextEnrichmentActivity }).passthrough().transform((payload) => payload.data),
]);
const IncidentOperationsState = z.object({
  schema_version: z.literal("kaiops.operations-state.v1"),
  incident_id: z.string().uuid(), lifecycle_state: z.string().min(1),
  context: JsonRecord, investigation: JsonRecord,
  requirements: RecordList, requirement_history: RecordList,
  resolution: JsonRecord, approval: JsonRecord,
  updated_at: z.string().or(z.date()),
}).passthrough();

type Contract = { method?: string; path: RegExp; schema: ZodTypeAny; name: string };

const contracts: readonly Contract[] = [
  { method: "GET", path: /^\/api-gateway\/auth\/config$/, schema: AuthConfig, name: "auth-config" },
  { method: "GET", path: /^\/api-gateway\/auth\/me$/, schema: AuthenticatedUser, name: "authenticated-user" },
  { method: "POST", path: /^\/api-gateway\/auth\/login$/, schema: Login, name: "login" },
  { method: "POST", path: /^\/api-gateway\/auth\/refresh$/, schema: Refresh, name: "token-refresh" },
  { path: /^\/api-gateway\/auth\/logout$/, schema: ObjectResponse, name: "logout" },
  { method: "GET", path: /^\/api-gateway\/healthz$/, schema: Health, name: "health" },
  { method: "GET", path: /^\/api-gateway\/operations\/queue-health$/, schema: QueueHealth, name: "queue-health" },
  { method: "GET", path: /^\/api-gateway\/incidents\/[0-9a-f-]+\/context-gaps$/i, schema: GatewayContextEnrichmentActivity, name: "context-enrichment-activity" },
  { method: "GET", path: /^\/api-gateway\/incidents\/[0-9a-f-]+\/operations-state$/i, schema: IncidentOperationsState, name: "incident-operations-state" },
  { method: "POST", path: /^\/api-gateway\/evaluations\/by-recommendation\/[0-9a-f-]+\/feedback$/i, schema: EvaluationFeedback, name: "evaluation-feedback" },
  { method: "POST", path: /^\/context-agent\/collect$/, schema: CollectedContext, name: "collected-context" },
  { method: "POST", path: /^\/resolution-agent\/resolve$/, schema: ResolutionRecommendation, name: "resolution-recommendation" },
  { method: "POST", path: /^\/api-gateway\/analysis\/alerts\/[0-9a-f-]+\/regenerate$/i, schema: AnalysisRegenerationAccepted, name: "analysis-regeneration-accepted" },
  { method: "GET", path: /^\/api-gateway\/analysis\/requests\/[0-9a-f-]+\/status$/i, schema: AnalysisRegenerationStatus, name: "analysis-regeneration-status" },
  { method: "POST", path: /^\/api-gateway\/analysis\/context\/collect$/, schema: GatewayCollectedContext, name: "gateway-collected-context" },
  { method: "POST", path: /^\/api-gateway\/analysis\/resolution\/resolve$/, schema: GatewayResolutionRecommendation, name: "gateway-resolution-recommendation" },
  { method: "POST", path: /^\/api-gateway\/analysis\/resolution-catalog\/(?:relevant|select)$/, schema: GatewayObjectResponse, name: "gateway-resolution-catalog" },
  { path: /^\/(?:api-gateway|monitoring-adapter)\/alerts(?:\/|$)/, schema: ObjectOrList, name: "alerts" },
  { path: /^\/api-gateway\/landing-pad(?:\/|$)/, schema: RowsEnvelope, name: "landing-pad" },
  { path: /^\/api-gateway\/incidents(?:\/|$)/, schema: ObjectOrList, name: "incidents" },
  { path: /^\/api-gateway\/approval(?:\/|$)/, schema: ObjectResponse, name: "approvals" },
  { path: /^\/api-gateway\/remediation(?:\/|$)/, schema: ObjectResponse, name: "remediation" },
  { path: /^\/api-gateway\/applications(?:\/|$)/, schema: ObjectOrList, name: "applications" },
  { path: /^\/api-gateway\/rag(?:\/|$)/, schema: ObjectOrList, name: "knowledge" },
  { path: /^\/api-gateway\/knowledge-pack(?:\/|$)/, schema: ObjectResponse, name: "knowledge-pack" },
  { path: /^\/api-gateway\/onboarding(?:\/|$)/, schema: ObjectOrList, name: "onboarding" },
  { path: /^\/api-gateway\/observability(?:\/|$)/, schema: ObjectOrList, name: "observability" },
  { path: /^\/api-gateway\/sample(?:\/|$)/, schema: ObjectOrList, name: "samples" },
  { path: /^\/api-gateway\/model(?:\/|$)/, schema: ObjectResponse, name: "model-routing" },
  { path: /^\/api-gateway\/users(?:\/|$)/, schema: ObjectOrList, name: "users" },
  { path: /^\/api-gateway\/roles(?:\/|$)/, schema: ObjectOrList, name: "roles" },
];

function normalizedPath(endpoint: string): string {
  return endpoint.split("?", 1)[0];
}

export function parseInternalApiResponse(endpoint: string, method: string, payload: unknown): unknown {
  const path = normalizedPath(endpoint);
  const normalizedMethod = method.toUpperCase();
  const contract = contracts.find((candidate) => (!candidate.method || candidate.method === normalizedMethod) && candidate.path.test(path));
  if (!contract) {
    throw new ApiValidationError(path, 1, `No Zod contract is registered for ${normalizedMethod} ${path}.`);
  }
  const parsed = contract.schema.safeParse(payload);
  if (!parsed.success) {
    throw new ApiValidationError(path, parsed.error.issues.length, `${contract.name} response failed validation.`);
  }
  return parsed.data;
}

export const internalApiContractCount = contracts.length;
