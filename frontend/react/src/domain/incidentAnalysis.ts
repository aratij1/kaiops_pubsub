type UnknownRecord = Record<string, any>;
const record = (value: unknown): UnknownRecord => value && typeof value === "object" && !Array.isArray(value) ? value as UnknownRecord : {};
const placeholders = new Set(["", "-", "undefined", "null", "none", "n/a", "na", "unknown", "tbd"]);

function clean(value: unknown, fallback = ""): string {
  if (Array.isArray(value)) {
    const values = [...new Set(value.map((item) => clean(item)).filter(Boolean))];
    return values.length ? values.join("; ") : fallback;
  }
  if (value && typeof value === "object") {
    const source = value as UnknownRecord;
    for (const key of ["summary", "description", "observed_impact", "impact_summary", "customer_impact", "service_impact", "root_cause", "cause", "mechanism", "reasoning", "content", "value"]) {
      const text = clean(source[key]);
      if (text) return text;
    }
    return fallback;
  }
  const text = String(value ?? "").trim();
  return placeholders.has(text.toLowerCase()) ? fallback : text;
}

/** Canonical display projection. It never promotes a hypothesis to a confirmed RCA. */
export function canonicalIncidentAnalysis(workflow: unknown, alertRow: unknown = null) {
  const root = record(workflow);
  const recommendation = record(root.recommendation);
  const metadata = record(recommendation.metadata);
  const contextMetadata = record(record(root.context).metadata);
  const discovery = record(contextMetadata.discovery_report);
  const report = record(discovery.report);
  const hypotheses = Array.isArray(report.hypotheses) ? report.hypotheses.map(record) : [];
  const rca = record(metadata.rca_analysis);
  const impactAnalysis = record(metadata.impact_analysis);
  const remediation = record(metadata.remediation_analysis);
  const confirmedRootCause = clean(rca.root_cause || recommendation.root_cause || root.root_cause);
  const hypothesis = hypotheses.find((item) => clean(item.cause));
  const externalKnowledgeUsed = Boolean(rca.external_knowledge_used || report.external_knowledge_used || metadata.external_knowledge_used);
  const externalKnowledgeEligible = Boolean(report.external_knowledge_eligible || metadata.external_knowledge_eligible);
  const externalKnowledgeError = clean(report.external_knowledge_error || metadata.external_knowledge_error);
  const rcaStatus = String(metadata.rca_status || "").trim().toLowerCase();
  return {
    rootCause: confirmedRootCause || (hypothesis ? `Hypothesis (not confirmed): ${clean(hypothesis.cause)}` : "RCA pending: available evidence is insufficient for a grounded conclusion."),
    impact: clean(impactAnalysis.impact_summary || impactAnalysis.customer_impact || impactAnalysis.service_impact || recommendation.impact || root.impact, "Impact not established from current evidence."),
    action: clean(remediation.recommended_action || recommendation.recommended_action || root.recommended_action, "Recommended action pending grounded RCA."),
    rca,
    impactAnalysis,
    remediation,
    status: rcaStatus === "insufficient_evidence" ? "insufficient-evidence" : rcaStatus === "grounded" || confirmedRootCause ? "resolved-analysis" : hypothesis ? "hypothesis" : "insufficient-evidence",
    confidence: Number(recommendation.confidence ?? rca.confidence_score ?? hypothesis?.confidence ?? 0),
    externalKnowledgeUsed,
    externalKnowledgeEligible,
    externalKnowledgeError,
    externalKnowledgeStatus: externalKnowledgeUsed ? "used" : externalKnowledgeError ? `failed: ${externalKnowledgeError}` : externalKnowledgeEligible ? "eligible; no configured external evidence returned" : "not required",
    externalToolsUsed: Array.isArray(metadata.external_tools_used) ? metadata.external_tools_used : Array.isArray(report.external_tools_used) ? report.external_tools_used : [],
    service: record(alertRow).service || record(root.alert).service || metadata.service || "unknown",
  };
}
