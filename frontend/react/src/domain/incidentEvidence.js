function object(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function rows(value) {
  if (Array.isArray(value)) return value.filter((item) => item && typeof item === "object");
  return Object.values(object(value)).flatMap((item) => Array.isArray(item) ? item : []);
}

export function canonicalIncidentEvidence(workflow) {
  const root = object(workflow);
  const context = object(root.context);
  const contextMetadata = object(context.metadata || root.context_metadata);
  const recommendation = object(root.recommendation);
  const metadata = object(recommendation.metadata);
  const analysis = object(metadata.rca_analysis);
  const investigation = object(metadata.iterative_investigation || metadata.investigation_report);
  const plan = object(metadata.execution_plan);
  const integrity = object(root.investigation_integrity || root.projection_payload?.investigation_integrity);
  const acceptedIds = new Set((Array.isArray(analysis.evidence_used) ? analysis.evidence_used : []).map(String));
  const evidence = rows(contextMetadata.context_evidence).map((item, index) => {
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
      accepted: Boolean(id && acceptedIds.has(id)),
    };
  });
  const missing = Array.isArray(analysis.missing_evidence) ? analysis.missing_evidence.map(String) : [];
  const conflicting = Array.isArray(analysis.conflicting_evidence)
    ? analysis.conflicting_evidence.map(String)
    : Array.isArray(metadata.conflicting_evidence) ? metadata.conflicting_evidence.map(String) : [];
  const conclusive = investigation.conclusive === true && String(investigation.status || "").toLowerCase() === "conclusive";
  const grounded = String(metadata.rca_status || "").toLowerCase() === "grounded" && acceptedIds.size > 0;
  const integrityVerified = integrity.status === "verified";
  const executionReady = integrityVerified && conclusive && grounded
    && plan.execution_ready === true && plan.mutating === true
    && Array.isArray(plan.readiness_blocks) && plan.readiness_blocks.length === 0;
  return {
    analysis, evidence, missing, conflicting,
    sources: object(contextMetadata.context_sources),
    acceptedEvidenceIds: [...acceptedIds],
    conclusive, grounded, integrity, integrityVerified, executionReady,
    confidence: grounded ? Number(investigation?.conclusion?.confidence || recommendation.confidence || 0) : 0,
  };
}
