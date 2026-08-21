import { describe, expect, it } from "vitest";

import { breadcrumbForPath, LEGACY_REDIRECTS, NAVIGATION_GROUPS, NAVIGATION_ITEMS, PATH_BY_TAB, searchNavigation, tabForPath } from "./navigation";
import { allowedLegacyTabsForRole, canAccessDestination, canAccessTab, permissionExplanation } from "./permissions";

describe("authoritative navigation", () => {
  it("has unique canonical paths and destination identifiers", () => {
    expect(new Set(NAVIGATION_ITEMS.map((item) => item.path)).size).toBe(NAVIGATION_ITEMS.length);
    expect(new Set(NAVIGATION_ITEMS.map((item) => item.id)).size).toBe(NAVIGATION_ITEMS.length);
    expect(NAVIGATION_GROUPS.map((group) => group.label)).toEqual(["Review work", "Administration"]);
  });

  it("maps every route through its legacy compatibility tab", () => {
    for (const item of NAVIGATION_ITEMS) {
      expect(tabForPath(item.path)).toBe(item.legacyTab);
      expect(PATH_BY_TAB[item.legacyTab]).toBeTruthy();
    }
  });

  it("redirects legacy approval and page aliases to canonical bookmarks", () => {
    expect(LEGACY_REDIRECTS).toContainEqual({ from: "/approval", to: "/approvals" });
    expect(LEGACY_REDIRECTS).toContainEqual({ from: "/approval-queue-legacy", to: "/approvals" });
    expect(LEGACY_REDIRECTS).toContainEqual({ from: "/stream", to: "/alerts" });
  });

  it("keeps restricted destinations out of role navigation and explains why", () => {
    expect(canAccessTab("hitl_reviewer", "home")).toBe(true);
    expect(canAccessDestination("hitl_reviewer", "alerts")).toBe(true);
    expect(canAccessDestination("hitl_reviewer", "admin")).toBe(false);
    expect(allowedLegacyTabsForRole("hitl_reviewer")).toEqual(["home", "stream", "summary", "approval", "closed", "copilot"]);
    expect(allowedLegacyTabsForRole("administrator")).toContain("executive");
    expect(permissionExplanation("hitl_reviewer", "admin")).toMatch(/not available.*hitl reviewer/i);
  });

  it("uses the same permitted registry for global navigation search", () => {
    expect(searchNavigation("connectors", "administrator").map((item) => item.id)).toEqual(["applications"]);
    expect(searchNavigation("connectors", "hitl_reviewer")).toEqual([]);
    expect(searchNavigation("human gate", "administrator").map((item) => item.id)).toEqual(["approvals"]);
  });

  it("derives breadcrumbs and contextual workflow relationships", () => {
    expect(breadcrumbForPath("/approvals").map((item) => item.label)).toEqual(["Review work", "My Approvals"]);
    expect(NAVIGATION_ITEMS.find((item) => item.id === "incidents")?.related).toEqual(["alerts", "approvals"]);
  });
});
