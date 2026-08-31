import { describe, expect, it } from "vitest";
import { incidentDraftHasSubstantiveContent, simpleIncidentReport } from "./incidentReport";

describe("incident report presentation", () => {
  it("reduces a technical report to the operator summary fields", () => {
    const report = simpleIncidentReport(`# Checkout outage
Incident ID: INC-42
Service: checkout-api
## Root cause
- Exhausted database pool
## Recommended response
- Restart the pool and validate checkout health`);

    expect(report).toContain("Incident: INC-42");
    expect(report).toContain("Root cause: Exhausted database pool");
    expect(report).toContain("Recommended action: Restart the pool");
  });

  it("rejects an empty report shell as non-substantive", () => {
    expect(incidentDraftHasSubstantiveContent("# Incident report")).toBe(false);
    expect(incidentDraftHasSubstantiveContent("# Incident report\nService owner confirmed recovery after rollback and validation.")).toBe(true);
  });
});
