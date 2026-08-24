import { describe, expect, it } from "vitest";
import type { IncidentRow } from "../../app/routeRuntime";
import { evidenceGraphFromIncident } from "./IncidentDecisionWorkspace";

describe("incident evidence graph", () => {
  it("preserves evidence certainty instead of promoting hypotheses", () => {
    const row = {
      projection_payload: { evidence_graph: {
        nodes: [
          { id: "deploy", label: "Deployment v2.41", kind: "observed_fact", source: "deploy/audit/41" },
          { id: "pool", label: "Pool exhaustion", relationship_source: "inferred", source: "kai-analysis" },
          { id: "mysql", label: "MySQL saturation", kind: "unverified hypothesis", source: "metrics-gap" },
        ],
        edges: [
          { source: "deploy", target: "pool", kind: "strong correlation" },
          { source: "pool", target: "mysql", kind: "unverified hypothesis" },
        ],
      } },
    } as unknown as IncidentRow;
    const graph = evidenceGraphFromIncident(row);
    expect(graph.nodes.map((node) => node.kind)).toEqual(["observed_fact", "ai_inferred", "hypothesis"]);
    expect(graph.edges[1].kind).toBe("hypothesis");
  });

  it("does not fabricate nodes when the backend has no causal graph", () => {
    expect(evidenceGraphFromIncident({ projection_payload: {} } as IncidentRow)).toEqual({ nodes: [], edges: [] });
  });
});
