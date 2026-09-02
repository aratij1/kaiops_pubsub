import { describe, expect, it } from "vitest";
import { isActionableInboxIncident } from "./IncidentsRoute";

describe("Unified Inbox actionability", () => {
  it("excludes warning incidents and admits high or critical incidents", () => {
    expect(isActionableInboxIncident({ severity: "warning" } as any)).toBe(false);
    expect(isActionableInboxIncident({ severity: "high" } as any)).toBe(true);
    expect(isActionableInboxIncident({ severity: "critical" } as any)).toBe(true);
  });

  it("excludes incidents explicitly classified as non-actionable", () => {
    expect(isActionableInboxIncident({
      severity: "critical",
      projection_payload: { event_payload: { incident_candidate: { actionable: false } } },
    } as any)).toBe(false);
  });
});
