import { describe, expect, it } from "vitest";

import { durableIncidentId, durableIncidentPath } from "./incidentNavigation";

describe("durable incident navigation", () => {
  it("uses and URL-encodes the durable incident identifier", () => {
    expect(durableIncidentPath({ incident_id: "tenant/a incident" })).toBe("/incidents/tenant%2Fa%20incident");
  });

  it("reads a linked incident projection without treating an alert id as the destination", () => {
    expect(durableIncidentPath({ id: "alert-id", incident_projection: { incident_id: "incident-id" } })).toBe("/incidents/incident-id");
  });

  it("returns an explicit unavailable result when identity is missing", () => {
    expect(durableIncidentId({})).toBe("");
    expect(durableIncidentPath({})).toBeNull();
  });
});
