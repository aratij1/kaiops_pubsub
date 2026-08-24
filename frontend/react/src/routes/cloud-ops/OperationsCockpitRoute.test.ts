import { describe, expect, it } from "vitest";
import { aggregateProjectReadiness } from "./OperationsCockpitRoute";

describe("project autonomy readiness", () => {
  it("averages returned service dimensions", () => {
    const result = aggregateProjectReadiness([
      { project_id: "p", service_id: "a", environment: "prod", readiness_state: "OPERABLE", overall_score: .8, autonomy_score: .6, scores: {}, dimensions: { monitoring: 1, traces: 0 } },
      { project_id: "p", service_id: "b", environment: "prod", readiness_state: "DRAFT", overall_score: .4, autonomy_score: .2, scores: {}, dimensions: { monitoring: .5, traces: .5 } },
    ]);
    expect(result.operational).toBeCloseTo(.6); expect(result.autonomy).toBeCloseTo(.4); expect(result.dimensions).toEqual({ monitoring: .75, traces: .25 });
  });
  it("does not fabricate readiness without rows", () => { expect(aggregateProjectReadiness([])).toEqual({ operational: 0, autonomy: 0, dimensions: {} }); });
});
