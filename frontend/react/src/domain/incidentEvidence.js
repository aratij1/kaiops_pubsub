function object(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function rows(value) {
  if (Array.isArray(value)) return value.filter((item) => item && typeof item === "object");
  return Object.values(object(value)).flatMap((item) => Array.isArray(item) ? item : []);
}

export function isTraceableEvidenceCitation(value) {
  const citation = String(value || "").trim().toLowerCase();
  return Boolean(citation) && !["context://", "unknown://", "unavailable://"].some((prefix) => citation.startsWith(prefix));
}

export function canonicalIncidentEvidence(workflow) {
  const root = object(workflow);
  const parsedContract = IncidentInvestigationV1.safeParse(root.incident_investigation);
  const contract = parsedContract.success ? parsedContract.data : null;
  const context = object(root.context);
  const contextMetadata = object(context.metadata || root.context_metadata);
  const recommendation = object(root.recommendation);
  const metadata = object(recommendation.metadata);
  const analysis = object(metadata.rca_analysis);
  const investigation = object(metadata.iterative_investigation || metadata.investigation_report);
  const integrity = object(root.investigation_integrity || root.projection_payload?.investigation_integrity);
  const acceptedIds = new Set(
    (contract?.accepted_evidence_ids || (Array.isArray(analysis.evidence_used) ? analysis.evidence_used : [])).map(String),
  );
  const evidence = (contract?.context_evidence || rows(contextMetadata.context_evidence)).map((item, index) => {
    const id = String(item.evidence_id || item.id || "").trim();
    const freshness = String(item.freshness || "unknown").toLowerCase();
    const historical = item.current_observation === false || item.epistemic_role === "historical_knowledge";
    return {
      ...item,
      id: id || `unidentified-evidence-${index + 1}`,
      source: String(item.source_id || item.source || item.connector || "unknown"),
      timestamp: item.observed_at || item.collected_at || "",
      citation: String(item.citation || ""),
      freshness,
      cached: historical || freshness === "stale",
      accepted: Boolean(id && acceptedIds.has(id) && isTraceableEvidenceCitation(item.citation)),
    };
  });
  const missing = contract?.missing_evidence || (Array.isArray(analysis.missing_evidence) ? analysis.missing_evidence.map(String) : []);
  const conflicting = contract?.conflicting_evidence || (Array.isArray(analysis.conflicting_evidence)
    ? analysis.conflicting_evidence.map(String)
    : Array.isArray(metadata.conflicting_evidence) ? metadata.conflicting_evidence.map(String) : []);
  const conclusive = contract
    ? contract.investigation_conclusive && contract.investigation_status === "conclusive"
    : investigation.conclusive === true && String(investigation.status || "").toLowerCase() === "conclusive";
  const traceableAcceptedCount = evidence.filter((item) => item.accepted).length;
  const grounded = contract
    ? contract.rca_status === "grounded" && traceableAcceptedCount > 0
    : String(metadata.rca_status || "").toLowerCase() === "grounded" && traceableAcceptedCount > 0;
  const integrityVerified = integrity.status === "verified";
  const contextReady = Boolean(contract && integrityVerified && contract.readiness.context_ready);
  const rcaReady = Boolean(contextReady && contract?.readiness.rca_ready && conclusive && grounded);
  const resolutionReady = Boolean(rcaReady && contract?.readiness.resolution_ready);
  const approvalReady = Boolean(resolutionReady && contract?.readiness.approval_ready);
  const executionReady = Boolean(approvalReady && contract?.execution_ready
    && contract?.readiness.execution_ready && contract.readiness_blocks.length === 0);
  const validationReady = Boolean(executionReady && contract?.readiness.validation_ready);
  const closureReady = Boolean(validationReady && contract?.readiness.closure_ready);
  const confidenceKind = String(metadata.confidence_kind || (
    conclusive && grounded ? "confirmed_rca" : "leading_hypothesis"
  )).trim().toLowerCase();
  const confidenceActionable = metadata.confidence_actionable === true && conclusive && grounded;
  // The recommendation is the canonical projection of the completed
  // investigation. Older nested model/evaluation scores must not override it.
  const diagnosticConfidence = Number(
    recommendation.confidence
    ?? investigation?.conclusion?.confidence
    ?? analysis.confidence_score
    ?? 0,
  );
  return {
    analysis, evidence, missing, conflicting,
    sources: object(contextMetadata.context_sources),
    acceptedEvidenceIds: [...acceptedIds],
    conclusive, grounded, integrity, integrityVerified,
    contextReady, rcaReady, resolutionReady, approvalReady, executionReady, validationReady, closureReady,
    contract, contractValid: parsedContract.success,
    contractError: parsedContract.success ? null : "Investigation contract invalid",
    // Confidence describes the bounded diagnostic assessment. Grounding and
    // execution readiness remain separate, stricter booleans so showing an
    // honest low/ungrounded score can never authorize remediation.
    confidence: Number.isFinite(diagnosticConfidence) ? diagnosticConfidence : 0,
    confidenceGrounded: grounded,
    confidenceKind,
    confidenceActionable,
    confidenceLabel: confidenceKind === "confirmed_rca" ? "Confirmed RCA confidence" : "Leading hypothesis confidence",
  };
}
import { IncidentInvestigationV1 } from "../schemas/incidentInvestigation";
