import { describe, expect, it } from "vitest";

import { buildIncidentGroupQuery } from "./incidentGroupQuery";

describe("buildIncidentGroupQuery", () => {
  it("omits unfiltered values and normalizes pagination", () => {
    expect(buildIncidentGroupQuery({ limit: 20, cursor: " next " }, {
      risk_tier: "all",
      execution_mode: "all",
      transport_provider: "all",
      status: "all",
      service: " ",
    })).toBe("limit=20&cursor=next");
  });

  it("preserves explicit incident filters", () => {
    expect(buildIncidentGroupQuery({}, {
      risk_tier: "high",
      execution_mode: "approval",
      transport_provider: "temporal",
      status: "awaiting_approval",
      service: " api-gateway ",
    })).toBe(
      "limit=10&risk_tier=high&execution_mode=approval&transport_provider=temporal&status=awaiting_approval&service=api-gateway",
    );
  });
});
