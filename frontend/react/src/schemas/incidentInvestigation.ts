import { z } from "zod";

const ContextQuality = z.object({
  evidence_count: z.number().int().nonnegative(),
  category_coverage: z.number().min(0).max(1),
  rca_readiness_score: z.number().min(0).max(1).default(0),
  impact_readiness_score: z.number().min(0).max(1).default(0),
  rca_ready: z.boolean().default(false),
  impact_ready: z.boolean().default(false),
  freshness_score: z.number().min(0).max(1),
  provenance_score: z.number().min(0).max(1),
  independent_source_count: z.number().int().nonnegative(),
  direct_observation_count: z.number().int().nonnegative(),
  valid: z.boolean(),
  blocking_reasons: z.array(z.string()),
}).strict();

const ContextSource = z.object({
  source_id: z.string().min(1),
  category: z.string().min(1),
  connector: z.string().min(1),
  status: z.enum(["completed", "empty", "unavailable", "unauthorized", "misconfigured", "timed_out", "skipped"]),
  collected_at: z.string().datetime(),
  error: z.string().nullable().optional(),
}).strict();

const ContextEvidence = z.object({
  evidence_id: z.string().min(1),
  category: z.string().min(1),
  source_id: z.string().min(1),
  connector: z.string().min(1),
  tenant_id: z.string().min(1),
  project_id: z.string().min(1),
  service: z.string().min(1),
  resource_id: z.string().nullable().optional(),
  observed_at: z.string().datetime().nullable().optional(),
  collected_at: z.string().datetime(),
  observation_window: z.record(z.unknown()).nullable().optional(),
  freshness: z.enum(["fresh", "stale", "unknown"]),
  provenance: z.record(z.unknown()),
  citation: z.string().min(1),
  epistemic_role: z.enum(["current_observation", "historical_knowledge", "operator_assertion"]),
  current_observation: z.boolean(),
}).strict();

const InvestigationReadiness = z.object({
  context_ready: z.boolean(),
  rca_ready: z.boolean(),
  resolution_ready: z.boolean(),
  approval_ready: z.boolean(),
  execution_ready: z.boolean(),
  validation_ready: z.boolean(),
  closure_ready: z.boolean(),
  blocking_reasons: z.array(z.string()),
}).strict().superRefine((value, context) => {
  if (value.closure_ready && !value.validation_ready) context.addIssue({ code: z.ZodIssueCode.custom, message: "closure readiness requires validation readiness" });
  if (value.validation_ready && !value.execution_ready) context.addIssue({ code: z.ZodIssueCode.custom, message: "validation readiness requires execution readiness" });
  if (value.execution_ready && !value.approval_ready) context.addIssue({ code: z.ZodIssueCode.custom, message: "execution readiness requires approval readiness" });
  if (value.approval_ready && !value.resolution_ready) context.addIssue({ code: z.ZodIssueCode.custom, message: "approval readiness requires resolution readiness" });
  if (value.resolution_ready && !value.rca_ready) context.addIssue({ code: z.ZodIssueCode.custom, message: "resolution readiness requires RCA readiness" });
  if (value.rca_ready && !value.context_ready) context.addIssue({ code: z.ZodIssueCode.custom, message: "RCA readiness requires context readiness" });
  if (!value.execution_ready && !value.blocking_reasons.length) context.addIssue({ code: z.ZodIssueCode.custom, message: "blocked execution requires a blocking reason" });
});

export const IncidentInvestigationV1 = z.object({
  contract_version: z.literal("kaiops.incident-investigation.v1"),
  tenant_id: z.string().min(1),
  project_id: z.string().min(1),
  incident_id: z.string().uuid(),
  alert_id: z.string().uuid(),
  analysis_request_id: z.string().uuid(),
  context_snapshot_id: z.string().uuid(),
  context_fingerprint: z.string().regex(/^[0-9a-f]{64}$/),
  context_contract_version: z.string().min(1),
  context_collected_at: z.string().datetime(),
  context_expires_at: z.string().datetime(),
  context_quality: ContextQuality,
  context_sources: z.array(ContextSource),
  context_evidence: z.array(ContextEvidence),
  investigation_id: z.string().uuid(),
  investigation_status: z.enum(["pending", "investigating", "conclusive", "inconclusive", "failed"]),
  investigation_conclusive: z.boolean(),
  rca_version: z.number().int().positive(),
  rca_status: z.enum(["pending", "grounded", "insufficient_evidence", "invalid_model_output", "inconclusive"]),
  accepted_evidence_ids: z.array(z.string()),
  missing_evidence: z.array(z.string()),
  conflicting_evidence: z.array(z.string()),
  recommendation_id: z.string().uuid().nullable(),
  resolution_plan_id: z.string().uuid().nullable(),
  plan_fingerprint: z.string().regex(/^sha256:[0-9a-f]{64}$/).nullable(),
  execution_ready: z.boolean(),
  readiness_blocks: z.array(z.string()),
  approval_status: z.enum(["not_ready", "pending", "approved", "rejected", "stale"]),
  remediation_status: z.string(),
  validation_status: z.string(),
  readiness: InvestigationReadiness,
}).strict().superRefine((value, context) => {
  const evidenceIds = new Set(value.context_evidence.map((item) => item.evidence_id));
  if (value.accepted_evidence_ids.some((id) => !evidenceIds.has(id))) context.addIssue({ code: z.ZodIssueCode.custom, message: "accepted evidence is not present in snapshot" });
  if (Date.parse(value.context_expires_at) <= Date.parse(value.context_collected_at)) context.addIssue({ code: z.ZodIssueCode.custom, message: "context expiry must be after collection" });
  if (value.investigation_conclusive !== (value.investigation_status === "conclusive")) context.addIssue({ code: z.ZodIssueCode.custom, message: "investigation status is contradictory" });
  if (value.rca_status === "grounded" && !value.accepted_evidence_ids.length) context.addIssue({ code: z.ZodIssueCode.custom, message: "grounded RCA requires evidence" });
  if (value.execution_ready !== value.readiness.execution_ready) context.addIssue({ code: z.ZodIssueCode.custom, message: "execution readiness fields disagree" });
  if (value.execution_ready && (!value.investigation_conclusive || value.rca_status !== "grounded" || !value.recommendation_id || !value.resolution_plan_id || !value.plan_fingerprint || value.readiness_blocks.length)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "execution readiness lacks exact upstream bindings" });
  }
});

export type IncidentInvestigation = z.infer<typeof IncidentInvestigationV1>;
