import { describe, expect, it } from "vitest";
import { buildCommandResults } from "./KaiCommandPalette";

describe("Kai command results", () => {
  it("keeps administrator destinations searchable", () => { expect(buildCommandResults("service", "administrator").some((item) => item.path === "/cloud-ops/resources")).toBe(true); });
  it("does not expose administrator destinations to approvers", () => { expect(buildCommandResults("settings", "hitl_reviewer").some((item) => item.path === "/admin")).toBe(false); });
  it("offers governed Copilot handoff for free text", () => { const result = buildCommandResults("why is checkout failing", "hitl_reviewer").at(-1); expect(result).toMatchObject({ kind: "ask", path: "/copilot?query=why%20is%20checkout%20failing" }); });
});
