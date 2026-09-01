function object(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function rows(value) {
  if (Array.isArray(value)) return value.filter((item) => item && typeof item === "object");
  return Object.values(object(value)).flatMap((item) => Array.isArray(item) ? item : []);
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
      accepted: Boolean(id && acceptedIds.has(id)),
    };
  });
  const missing = contract?.missing_evidence || (Array.isArray(analysis.missing_evidence) ? analysis.missing_evidence.map(String) : []);
  const conflicting = contract?.conflicting_evidence || (Array.isArray(analysis.conflicting_evidence)
    ? analysis.conflicting_evidence.map(String)
    : Array.isArray(metadata.conflicting_evidence) ? metadata.conflicting_evidence.map(String) : []);
  const conclusive = contract
    ? contract.investigation_conclusive && contract.investigation_status === "conclusive"
    : investigation.conclusive === true && String(investigation.status || "").toLowerCase() === "conclusive";
  const grounded = contract
    ? contract.rca_status === "grounded" && acceptedIds.size > 0
    : String(metadata.rca_status || "").toLowerCase() === "grounded" && acceptedIds.size > 0;
  const integrityVerified = integrity.status === "verified";
  const executionReady = Boolean(contract && integrityVerified && conclusive && grounded
    && contract.execution_ready && contract.readiness.execution_ready
    && contract.readiness_blocks.length === 0);
  // recommendation.metadata carries two distinct, independently-populated
  // confidence signals: "rca_analysis.confidence_score" comes from the
  // older, always-present LLM RCA pipeline (see resolution_agent/graph.py
  // generate_rca/confidence_scoring), while "iterative_investigation" is
  // the bounded, evidence-grounded investigation graph and is the only one
  // that reflects the fuller evidence gathering (discovery-mcp + resolution
  // graph fixes). Because rca_analysis.confidence_score is always present
  // (even as a capped/legacy 0) and `??` only skips null/undefined, putting
  // it first silently wins over a real, differentiated
  // iterative_investigation confidence whenever the legacy score happened
  // to be 0 -- exactly the bug already fixed in RcaPanel.tsx/App.jsx for
  // their own confidence reads. Preferring iterative_investigation here
  // keeps this the single remaining confidence read consistent with those.
  const diagnosticConfidence = Number(
    investigation?.conclusion?.confidence
    ?? analysis.confidence_score
    ?? recommendation.confidence
    ?? 0,
  );
  return {
    analysis, evidence, missing, conflicting,
    sources: object(contextMetadata.context_sources),
    acceptedEvidenceIds: [...acceptedIds],
    conclusive, grounded, integrity, integrityVerified, executionReady,
    contract, contractValid: parsedContract.success,
    contractError: parsedContract.success ? null : "Investigation contract invalid",
    // Confidence describes the bounded diagnostic assessment. Grounding and
    // execution readiness remain separate, stricter booleans so showing an
    // honest low/ungrounded score can never authorize remediation.
    confidence: Number.isFinite(diagnosticConfidence) ? diagnosticConfidence : 0,
    confidenceGrounded: grounded,
  };
}
import { IncidentInvestigationV1 } from "../schemas/incidentInvestigation";
